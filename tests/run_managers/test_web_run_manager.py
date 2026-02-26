from unittest.mock import MagicMock, patch

import requests

from run_managers.common import RunMetadata
from run_managers.web import WebRunManager


def _make_metadata() -> RunMetadata:
    return RunMetadata(
        trigger_user_name="test-user",
        source="test",
        thread_context="hello",
        repo="my-repo",
    )


# ── constructor ───────────────────────────────────────────────────


def test_constructor_strips_trailing_slash():
    mgr = WebRunManager("https://api.example.com/")
    assert mgr.base_url == "https://api.example.com"


# ── create_run() ──────────────────────────────────────────────────


@patch("run_managers.web.requests.post")
def test_create_run_posts_and_returns_run_id(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"run_id": "abc-123"}
    mock_post.return_value = mock_resp

    mgr = WebRunManager("https://api.example.com")
    result = mgr.create_run(_make_metadata())

    assert result == {"run_id": "abc-123"}
    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert call_url == "https://api.example.com/runs"
    payload = mock_post.call_args[1]["json"]
    run_data = payload["run"]
    assert run_data["creator"] == "test-user"
    assert run_data["source"] == "test"
    assert run_data["thread_context"] == "hello"
    assert run_data["repo"] == "my-repo"


@patch("run_managers.web.requests.post")
def test_create_run_raises_on_http_error(mock_post):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    mock_post.return_value = mock_resp

    mgr = WebRunManager("https://api.example.com")
    try:
        mgr.create_run(_make_metadata())
        assert False, "Expected HTTPError"
    except requests.HTTPError:
        pass


# ── send_events() ─────────────────────────────────────────────────


@patch("run_managers.web.requests.post")
def test_send_events_posts_to_correct_url(mock_post):
    mock_resp = MagicMock()
    mock_post.return_value = mock_resp

    mgr = WebRunManager("https://api.example.com")
    events = [{"type": "log", "data": "ok"}]
    mgr.send_events("run-42", events)

    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert call_url == "https://api.example.com/runs/run-42/run_entries"
    payload = mock_post.call_args[1]["json"]
    assert payload == {"run_entry": {"data": {"type": "log", "data": "ok"}}}


@patch("run_managers.web.requests.post")
def test_send_events_swallows_exceptions(mock_post):
    mock_post.side_effect = requests.ConnectionError("offline")

    mgr = WebRunManager("https://api.example.com")
    mgr.send_events("run-42", [{"type": "log"}])  # should not raise
