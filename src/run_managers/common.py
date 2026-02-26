from dataclasses import dataclass


@dataclass
class RunMetadata:
    trigger_user_name: str
    source: str
    thread_context: str
    repo: str | None = None
    channel_id: str | None = None
    thread_ts: str | None = None
