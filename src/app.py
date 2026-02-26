import os
import signal

from dotenv import load_dotenv

load_dotenv()

import redis
from slack_bolt import App

from queues.queue import JobQueue
from job_producers.cli import CliJobProducer
from job_producers.slack import SlackJobProducer
from run_managers.interface import RunManagerType
from run_managers.fake import FakeRunManager
from run_managers.web import WebRunManager
from log_config import setup_logging

logger = setup_logging("app")

queue = JobQueue(redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, db=0))

web_run_manager_url = os.environ.get("WEB_RUN_MANAGER_URL")
if web_run_manager_url:
    run_manager = WebRunManager(web_run_manager_url)
    run_manager_type = RunManagerType.WEB
    logger.info(f"Using WebRunManager ({web_run_manager_url})")
else:
    run_manager = FakeRunManager()
    run_manager_type = RunManagerType.FAKE
    logger.info("WEB_RUN_MANAGER_URL not set — using FakeRunManager")

producers = [
    SlackJobProducer(
        queue=queue,
        slack_app=App(token=os.environ["SLACK_BOT_TOKEN"]),
        slack_app_token=os.environ["SLACK_APP_TOKEN"],
        run_manager=run_manager,
        run_manager_type=run_manager_type,
    ),
    CliJobProducer(
        queue=queue,
        prompt=os.environ.get("CLI_PROMPT", ""),
        run_manager=run_manager,
        run_manager_type=run_manager_type,
        repo=os.environ.get("CLI_REPO"),
    ),
]

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting producers")
    logger.info(f"Redis: {os.environ.get('REDIS_HOST', 'localhost')}:6379")
    logger.info("=" * 60)

    for p in producers:
        p.start()

    logger.info("All producers started")
    signal.pause()
