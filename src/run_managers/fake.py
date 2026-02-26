import uuid

from log_config import setup_logging
from run_managers.common import RunMetadata

logger = setup_logging("fake_run_manager")


class FakeRunManager:
    def create_run(self, metadata: RunMetadata) -> str:
        run_id = str(uuid.uuid4())
        logger.info(f"[FAKE] Created run {run_id} (source={metadata.source}, user={metadata.trigger_user_name})")
        return run_id

    def send_events(self, run_id: str, events: list[dict]) -> None:
        logger.info(f"[FAKE] Would send {len(events)} events for run {run_id} (skipped)")
