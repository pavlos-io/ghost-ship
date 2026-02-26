from enum import StrEnum
from typing import Iterator, Protocol, TypedDict, TypeVar


class ModelProvider(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class Job(TypedDict):
    thread_context: str
    trigger_user_name: str
    repo: str | None
    run_id: str
    run_manager_type: str
    model_provider: ModelProvider


J = TypeVar("J", bound=Job)


class PromptSource(Protocol[J]):
    def jobs(self) -> Iterator[J]: ...
    def context_block(self, job: J) -> str: ...
    def log_metadata(self, job: J) -> dict: ...
    def session_label(self, job: J) -> str: ...
    def reply(self, job: J, text: str) -> None: ...
    def reply_error(self, job: J, text: str) -> None: ...
