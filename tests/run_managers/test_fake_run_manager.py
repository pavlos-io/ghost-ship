import uuid

from run_managers.fake import FakeRunManager
from run_managers.common import RunMetadata


def _make_metadata() -> RunMetadata:
    return RunMetadata(
        trigger_user_name="test-user",
        source="test",
        thread_context="hello",
    )


# ── create_run() ──────────────────────────────────────────────────


def test_create_run_returns_valid_uuid():
    mgr = FakeRunManager()
    run_id = mgr.create_run(_make_metadata())
    uuid.UUID(run_id)  # raises if invalid


def test_create_run_returns_different_ids():
    mgr = FakeRunManager()
    ids = {mgr.create_run(_make_metadata()) for _ in range(5)}
    assert len(ids) == 5


# ── send_events() ─────────────────────────────────────────────────


def test_send_events_does_not_raise():
    mgr = FakeRunManager()
    mgr.send_events("fake-id", [{"type": "log", "data": "ok"}])
