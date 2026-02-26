import os
from enum import StrEnum
from typing import Protocol

from run_managers.common import RunMetadata
from run_managers.fake import FakeRunManager
from run_managers.web import WebRunManager


class RunManagerType(StrEnum):
    WEB = "web"
    FAKE = "fake"


class RunManager(Protocol):
    def create_run(self, metadata: RunMetadata) -> str: ...
    def send_events(self, run_id: str, events: list[dict]) -> None: ...


def build_run_manager(run_manager_type: RunManagerType) -> RunManager:
    if run_manager_type == RunManagerType.WEB:
        return WebRunManager(os.environ["WEB_RUN_MANAGER_URL"])

    if run_manager_type == RunManagerType.FAKE:
        return FakeRunManager()

    raise ValueError(f"Unknown run_manager_type: {run_manager_type}")
