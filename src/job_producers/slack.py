import json
import re
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from context_providers.registry import build_registry
from queues.queue import JobQueue
from run_managers.interface import RunManager, RunManagerType
from run_managers.common import RunMetadata
from log_config import setup_logging
from prompt_sources.interface import ModelProvider
from prompt_sources.slack import SlackJob
from thread_parser import format_thread, parse_thread, trim_thread

logger = setup_logging("slack_producer")


class SlackJobProducer:
    def __init__(self, queue: JobQueue, slack_app: App, slack_app_token: str, run_manager: RunManager, run_manager_type: RunManagerType):
        self.queue = queue
        self.app = slack_app
        self.run_manager = run_manager
        self.run_manager_type = run_manager_type
        self.handler = SocketModeHandler(slack_app, slack_app_token)
        self.app.event("app_mention")(self.handle_mention)

    def start(self) -> None:
        logger.info("Starting Slack producer in Socket Mode")
        self.queue.ping()
        self.handler.connect()

    def stop(self) -> None:
        self.handler.close()

    def handle_mention(self, event, client, say) -> None:
        start = time.time()
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        trigger_user: str = event.get("user", "unknown")

        logger.info("--- New mention received ---")
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
        users_map = self.build_users_map(client, user_ids)
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

        # Acknowledge in thread early (before enrichment latency)
        say(text="Got it, working on it...", thread_ts=thread_ts)

        # Enrich context with external providers (Sentry, etc.)
        try:
            registry = build_registry()
            enrichment = registry.enrich(context)
            if enrichment:
                context += enrichment
                logger.info(f"Context enriched ({len(enrichment)} chars)")
        except Exception:
            logger.warning("Context enrichment failed, continuing without", exc_info=True)

        # Create run in tracker before enqueuing
        trigger_user_name: str = users_map.get(trigger_user, trigger_user)
        metadata = RunMetadata(
            trigger_user_name=trigger_user_name,
            source="slack",
            thread_context=context,
            repo=repo,
            channel_id=channel,
            thread_ts=thread_ts,
        )
        try:
            run_id = self.run_manager.create_run(metadata)
        except Exception as e:
            logger.error(f"Failed to create run, not enqueuing job: {e}")
            return

        # Enqueue job to Redis
        job: SlackJob = {
            "channel_id": channel,
            "thread_ts": thread_ts,
            "trigger_user": trigger_user,
            "trigger_user_name": trigger_user_name,
            "thread_context": context,
            "repo": repo,
            "run_id": run_id,
            "run_manager_type": self.run_manager_type,
            "model_provider": ModelProvider.CLAUDE,
        }
        self.queue.enqueue(job)
        elapsed = time.time() - start
        logger.info(f"Mention handled in {elapsed:.2f}s")

    @staticmethod
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

