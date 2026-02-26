import requests

from log_config import setup_logging
from run_managers.common import RunMetadata

logger = setup_logging("web_run_manager")


class WebRunManager:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def create_run(self, metadata: RunMetadata) -> str:
        """POST to create a run. Returns run_id. Raises on failure."""
        url = f"{self.base_url}/runs"
        payload = {
            'run': {
                "creator": metadata.trigger_user_name,
                "source": metadata.source,
                "thread_context": metadata.thread_context,
                "repo": metadata.repo,
                "channel_id": metadata.channel_id,
                "thread_ts": metadata.thread_ts,
            }
        }
        logger.info(f"Creating run at {url}")
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        run_id = resp.json()
        logger.info(f"Run created: {run_id}")
        return run_id

    def send_events(self, run_id: str, events: list[dict]) -> None:
        """POST each event to run_entries. Non-fatal — logs errors but does not raise."""
        url = f"{self.base_url}/runs/{run_id}/run_entries"
        logger.info(f"Sending {len(events)} events for run {run_id}")
        for event in events:
            payload = {'run_entry': {'data': event}}
            try:
                resp = requests.post(url, json=payload, timeout=10)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to send event for run {run_id}: {e}")
        logger.info(f"Events sent for run {run_id}")
