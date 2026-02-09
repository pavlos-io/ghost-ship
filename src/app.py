import json
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

import redis
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from log_config import setup_logging
from thread_parser import format_thread, parse_thread, trim_thread

logger = setup_logging("app")

app = App(token=os.environ["SLACK_BOT_TOKEN"])
r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, db=0)


def build_users_map(client, user_ids: set[str]) -> dict[str, str]:
    """Resolve Slack user IDs to display names."""
    users_map = {}
    for uid in user_ids:
        try:
            info = client.users_info(user=uid)
            profile = info["user"]["profile"]
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or uid
            )
            users_map[uid] = name
            logger.debug(f"Resolved user {uid} → {name}")
        except Exception as e:
            logger.warning(f"Failed to resolve user {uid}: {e}")
            users_map[uid] = uid
    return users_map


@app.event("app_mention")
def handle_mention(event, client, say):
    start = time.time()
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    trigger_user = event.get("user", "unknown")

    logger.info(f"--- New mention received ---")
    logger.info(f"Channel: {channel} | Thread: {thread_ts} | User: {trigger_user}")
    logger.debug(f"Raw event: {json.dumps(event, indent=2)}")

    # Fetch thread messages
    try:
        logger.info("Fetching thread messages...")
        result = client.conversations_replies(channel=channel, ts=thread_ts)
        messages = result.get("messages", [])
        logger.info(f"Fetched {len(messages)} message(s) from thread")
        for i, msg in enumerate(messages):
            logger.debug(f"  Message {i}: user={msg.get('user', '?')} text={msg.get('text', '')[:100]}")
    except Exception as e:
        logger.error(f"Failed to fetch thread: {e}", exc_info=True)
        say(text=f"Sorry, I couldn't read the thread: {e}", thread_ts=thread_ts)
        return

    # Collect user IDs: message authors + mentioned users
    user_ids = {m.get("user") for m in messages if m.get("user")}
    user_ids.add(trigger_user)
    for msg in messages:
        user_ids.update(re.findall(r"<@(\w+)>", msg.get("text", "")))
    logger.info(f"Resolving {len(user_ids)} user ID(s)...")
    users_map = build_users_map(client, user_ids)
    logger.info(f"Users map: {users_map}")

    # Extract repo reference (repo:repo-name) from the trigger message
    trigger_text = event.get("text", "")
    repo_match = re.search(r"repo:([\w.-]+)", trigger_text)
    repo = repo_match.group(1) if repo_match else None
    if repo:
        logger.info(f"Repo reference found: {repo}")

    # Parse and trim thread
    logger.info("Parsing thread...")
    parsed = parse_thread(messages, users_map)
    logger.info(f"Parsed {len(parsed)} message(s)")

    trimmed = trim_thread(parsed)
    logger.info(f"Trimmed to {len(trimmed)} message(s) (from {len(parsed)})")

    context = format_thread(trimmed)
    # Strip repo:... tokens from context so they don't confuse Claude
    if repo:
        context = re.sub(r"repo:[\w.-]+\s*", "", context)
    logger.debug(f"Formatted thread context:\n{context}")

    # Enqueue job to Redis
    job = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "trigger_user": trigger_user,
        "trigger_user_name": users_map.get(trigger_user, trigger_user),
        "thread_context": context,
        "repo": repo,
    }
    r.rpush("jobs", json.dumps(job))
    queue_len = r.llen("jobs")
    logger.info(f"Job enqueued | Queue length: {queue_len}")
    logger.debug(f"Job payload: {json.dumps(job, indent=2)}")

    # Acknowledge in thread
    say(text="Got it, working on it...", thread_ts=thread_ts)
    elapsed = time.time() - start
    logger.info(f"Mention handled in {elapsed:.2f}s")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Slack app in Socket Mode")
    logger.info(f"Redis: {os.environ.get('REDIS_HOST', 'localhost')}:6379")
    logger.info("=" * 60)

    try:
        r.ping()
        logger.info("Redis connection OK")
    except redis.ConnectionError as e:
        logger.error(f"Cannot connect to Redis: {e}")
        raise

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
