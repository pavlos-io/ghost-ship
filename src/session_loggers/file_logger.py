import json
import os
from datetime import datetime, timezone

from log_config import setup_logging

logger = setup_logging("session_logger")

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "sessions")


class FileSessionLogger:
    def __init__(self, sessions_dir: str = SESSIONS_DIR):
        self._sessions_dir = sessions_dir
        os.makedirs(self._sessions_dir, exist_ok=True)

    def save(self, events: list[dict], metadata: dict, label: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{label}.jsonl"
        filepath = os.path.join(self._sessions_dir, filename)

        with open(filepath, "w") as f:
            f.write(json.dumps({"type": "_metadata", **metadata}) + "\n")
            for event in events:
                f.write(json.dumps(event) + "\n")

        logger.info(f"Session log saved: {filepath} ({len(events)} events)")
