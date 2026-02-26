from typing import Protocol


class SessionLogger(Protocol):
    def save(self, events: list[dict], metadata: dict) -> None: ...
