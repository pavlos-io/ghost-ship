import json
from typing import Iterator

import redis
from slack_sdk import WebClient

from log_config import setup_logging
from prompt_sources.interface import Job


class SlackJob(Job):
    channel_id: str
    thread_ts: str
    trigger_user: str

logger = setup_logging("prompt_sources.slack")


class SlackPromptSource:
    def __init__(self, redis_client: redis.Redis, slack_client: WebClient):
        self._redis = redis_client
        self._slack = slack_client

    def jobs(self) -> Iterator[SlackJob]:
        while True:
            _, raw = self._redis.blpop(["jobs"], timeout=0)  # type: ignore[misc]
            job = json.loads(raw)
            queue_len = self._redis.llen("jobs")
            logger.info(f"Job received | Remaining in queue: {queue_len}")
            yield job

    def reply(self, job: SlackJob, text: str) -> None:
        self._slack.chat_postMessage(
            channel=job["channel_id"],
            thread_ts=job["thread_ts"],
            text=text,
        )
        logger.info("Result posted to Slack")

    def context_block(self, job: SlackJob) -> str:
        thread_context = job.get("thread_context", "(no context)")
        return (
            "## Slack thread context\n"
            "The following messages are from the Slack thread that triggered this task:\n\n"
            f"{thread_context}"
        )

    def log_metadata(self, job: SlackJob) -> dict:
        return {
            "thread_ts": job["thread_ts"],
            "channel_id": job["channel_id"],
            "trigger_user_name": job["trigger_user_name"],
            "repo": job.get("repo"),
        }

    def session_label(self, job: SlackJob) -> str:
        return job["thread_ts"]

    def reply_error(self, job: SlackJob, text: str) -> None:
        try:
            self._slack.chat_postMessage(
                channel=job["channel_id"],
                thread_ts=job["thread_ts"],
                text=f"Something went wrong: {text}",
            )
            logger.info("Error message posted to Slack")
        except Exception as e:
            logger.error(f"Failed to post error to Slack: {e}", exc_info=True)
