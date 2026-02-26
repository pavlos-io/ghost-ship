import json
from collections.abc import Mapping
from typing import Any

import redis

from log_config import setup_logging

logger = setup_logging("job_queue")


class JobQueue:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def ping(self) -> None:
        self.redis.ping()
        logger.info("Redis connection OK")

    def enqueue(self, job: Mapping[str, Any]) -> None:
        self.redis.rpush("jobs", json.dumps(job))
        queue_len = self.redis.llen("jobs")
        logger.info(f"Job enqueued | Queue length: {queue_len}")
        logger.debug(f"Job payload: {json.dumps(job, indent=2)}")
