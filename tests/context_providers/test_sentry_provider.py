from unittest.mock import MagicMock, patch

from context_providers.interface import ContextProviderReference
from context_providers.sentry_provider import SENTRY_URL_PATTERN, SentryProvider


# ── URL pattern extraction ──────────────────────────────────────────


def test_pattern_org_subdomain_url():
    m = SENTRY_URL_PATTERN.search("https://my-org.sentry.io/issues/12345/")
    assert m and m.group(1) == "12345"


def test_pattern_organizations_url():
    m = SENTRY_URL_PATTERN.search(
        "https://sentry.io/organizations/my-org/issues/67890/"
    )
    assert m and m.group(1) == "67890"


def test_pattern_no_match_on_plain_text():
    m = SENTRY_URL_PATTERN.search("issue 12345 is broken")
    assert m is None


def test_pattern_no_match_on_non_sentry_url():
    m = SENTRY_URL_PATTERN.search("https://example.com/issues/12345/")
    assert m is None


def test_pattern_extracts_from_surrounding_text():
    text = "look at https://acme.sentry.io/issues/99999/ for details"
    m = SENTRY_URL_PATTERN.search(text)
    assert m and m.group(1) == "99999"


def test_pattern_without_trailing_slash():
    m = SENTRY_URL_PATTERN.search("https://my-org.sentry.io/issues/11111")
    assert m and m.group(1) == "11111"


# ── extract() ───────────────────────────────────────────────────────


def _make_provider() -> SentryProvider:
    return SentryProvider(auth_token="fake-token")


def test_extract_returns_issue_ids():
    provider = _make_provider()
    text = "https://acme.sentry.io/issues/111/ and https://acme.sentry.io/issues/222/"
    refs = provider.extract(text)
    assert [str(r) for r in refs] == ["111", "222"]


def test_extract_deduplicates():
    provider = _make_provider()
    text = (
        "https://acme.sentry.io/issues/111/ "
        "https://acme.sentry.io/issues/111/ "
        "https://acme.sentry.io/issues/222/"
    )
    refs = provider.extract(text)
    assert [str(r) for r in refs] == ["111", "222"]


def test_extract_returns_empty_for_no_urls():
    provider = _make_provider()
    assert provider.extract("nothing here") == []


# ── constructor ─────────────────────────────────────────────────────


def test_constructor_sets_auth_header():
    provider = SentryProvider(auth_token="tok123")
    assert provider._session.headers["Authorization"] == "Bearer tok123"


def test_constructor_strips_trailing_slash():
    provider = SentryProvider(auth_token="t", base_url="https://sentry.io/api/0/")
    assert provider._base_url == "https://sentry.io/api/0"


def test_constructor_default_base_url():
    provider = SentryProvider(auth_token="t")
    assert "sentry.io" in provider._base_url


# ── resolve() ───────────────────────────────────────────────────────


SAMPLE_ISSUE = {
    "title": "ZeroDivisionError: division by zero",
    "status": "unresolved",
    "firstSeen": "2025-01-10T08:00:00Z",
    "lastSeen": "2025-01-15T12:00:00Z",
    "count": "42",
    "tags": [
        {"key": "environment", "value": "production"},
        {"key": "level", "value": "error"},
    ],
}

SAMPLE_EVENT = {
    "entries": [
        {
            "type": "exception",
            "data": {
                "values": [
                    {
                        "type": "ZeroDivisionError",
                        "value": "division by zero",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "app.py",
                                    "lineNo": 42,
                                    "function": "divide",
                                    "context_line": "return a / b",
                                }
                            ]
                        },
                    }
                ]
            },
        },
        {
            "type": "breadcrumbs",
            "data": {
                "values": [
                    {
                        "category": "http",
                        "message": "GET /api/divide",
                        "level": "info",
                        "timestamp": "2025-01-15T12:00:00Z",
                    }
                ]
            },
        },
        {
            "type": "request",
            "data": {
                "method": "GET",
                "url": "https://example.com/api/divide?a=1&b=0",
            },
        },
    ]
}


def _mock_session_get(issue_data, event_data):
    """Return a side_effect function that serves issue then event responses."""
    issue_resp = MagicMock()
    issue_resp.json.return_value = issue_data
    issue_resp.headers = {}

    event_resp = MagicMock()
    event_resp.json.return_value = event_data
    event_resp.headers = {}

    def side_effect(url, **kwargs):
        if "events/latest" in url:
            return event_resp
        return issue_resp

    return side_effect


def test_resolve_full_issue_with_event():
    provider = _make_provider()
    provider._session.get = MagicMock(
        side_effect=_mock_session_get(SAMPLE_ISSUE, SAMPLE_EVENT)
    )

    result = provider.resolve(ContextProviderReference("12345"))

    assert "## Sentry Issue 12345" in result
    assert "**Title:** ZeroDivisionError: division by zero" in result
    assert "**Status:** unresolved" in result
    assert "**First seen:** 2025-01-10" in result
    assert "**Last seen:** 2025-01-15" in result
    assert "**Event count:** 42" in result
    assert "`environment=production`" in result
    assert "`level=error`" in result
    # Exception
    assert "**Exception:** `ZeroDivisionError: division by zero`" in result
    # Stacktrace
    assert "app.py:42 in divide" in result
    assert "return a / b" in result
    # Breadcrumbs
    assert "**Breadcrumbs**" in result
    assert "GET /api/divide" in result
    # Request
    assert "**Request:** `GET https://example.com/api/divide?a=1&b=0`" in result


def test_resolve_issue_fetch_failure():
    provider = _make_provider()
    provider._session.get = MagicMock(side_effect=Exception("connection error"))

    result = provider.resolve(ContextProviderReference("99999"))

    assert "## Sentry Issue 99999" in result
    assert "Could not fetch issue details" in result


def test_resolve_event_fetch_failure():
    """Issue succeeds but event fails — should still return issue metadata."""
    provider = _make_provider()

    issue_resp = MagicMock()
    issue_resp.json.return_value = SAMPLE_ISSUE
    issue_resp.headers = {}

    def side_effect(url, **kwargs):
        if "events/latest" in url:
            raise Exception("event timeout")
        return issue_resp

    provider._session.get = MagicMock(side_effect=side_effect)

    result = provider.resolve(ContextProviderReference("12345"))

    assert "**Title:** ZeroDivisionError" in result
    assert "**Status:** unresolved" in result
    assert "Could not fetch latest event details" in result


def test_resolve_issue_without_tags():
    provider = _make_provider()
    issue = {
        "title": "Error",
        "status": "resolved",
        "firstSeen": "2025-01-01",
        "lastSeen": "2025-01-02",
        "count": "1",
    }
    provider._session.get = MagicMock(
        side_effect=_mock_session_get(issue, {"entries": []})
    )

    result = provider.resolve(ContextProviderReference("100"))

    assert "**Tags:**" not in result


def test_resolve_issue_with_missing_fields():
    """Missing optional fields in the issue dict should use defaults."""
    provider = _make_provider()
    # Must have at least one key so the dict is truthy (empty dict → treated as fetch failure)
    issue = {"id": "100"}
    provider._session.get = MagicMock(
        side_effect=_mock_session_get(issue, {"entries": []})
    )

    result = provider.resolve(ContextProviderReference("100"))

    assert "**Title:** Unknown" in result
    assert "**Status:** unknown" in result
    assert "**First seen:** N/A" in result


# ── _format edge cases ──────────────────────────────────────────────


def test_format_exception_without_stacktrace():
    provider = _make_provider()
    event = {
        "entries": [
            {
                "type": "exception",
                "data": {
                    "values": [
                        {"type": "ValueError", "value": "bad input", "stacktrace": {"frames": []}}
                    ]
                },
            }
        ]
    }
    provider._session.get = MagicMock(
        side_effect=_mock_session_get(SAMPLE_ISSUE, event)
    )

    result = provider.resolve(ContextProviderReference("1"))

    assert "**Exception:** `ValueError: bad input`" in result
    assert "**Stacktrace**" not in result


def test_format_breadcrumbs_limited_to_last_5():
    crumbs = [
        {"category": f"cat{i}", "message": f"msg{i}", "level": "info", "timestamp": f"t{i}"}
        for i in range(8)
    ]
    event = {"entries": [{"type": "breadcrumbs", "data": {"values": crumbs}}]}
    provider = _make_provider()
    provider._session.get = MagicMock(
        side_effect=_mock_session_get(SAMPLE_ISSUE, event)
    )

    result = provider.resolve(ContextProviderReference("1"))

    assert "msg0" not in result
    assert "msg1" not in result
    assert "msg2" not in result
    assert "msg3" in result
    assert "msg7" in result


def test_format_stacktrace_limited_to_last_10():
    frames = [
        {"filename": f"f{i}.py", "lineNo": i, "function": f"fn{i}", "context_line": ""}
        for i in range(15)
    ]
    event = {
        "entries": [
            {
                "type": "exception",
                "data": {"values": [{"type": "E", "value": "v", "stacktrace": {"frames": frames}}]},
            }
        ]
    }
    provider = _make_provider()
    provider._session.get = MagicMock(
        side_effect=_mock_session_get(SAMPLE_ISSUE, event)
    )

    result = provider.resolve(ContextProviderReference("1"))

    assert "f0.py" not in result
    assert "f4.py" not in result
    assert "f5.py" in result
    assert "f14.py" in result


# ── build_registry ──────────────────────────────────────────────────


def test_registry_registers_sentry_when_env_set():
    env = {"SENTRY_AUTH_TOKEN": "tok"}
    with patch.dict("os.environ", env, clear=True):
        from context_providers.registry import build_registry

        registry = build_registry()

    sentry_providers = [
        p for p in registry._providers if p.provider_type.value == "sentry"
    ]
    assert len(sentry_providers) == 1


def test_registry_skips_sentry_when_env_missing():
    with patch.dict("os.environ", {}, clear=True):
        from context_providers.registry import build_registry

        registry = build_registry()

    sentry_providers = [
        p for p in registry._providers if p.provider_type.value == "sentry"
    ]
    assert len(sentry_providers) == 0


def test_registry_uses_custom_base_url():
    env = {
        "SENTRY_AUTH_TOKEN": "tok",
        "SENTRY_BASE_URL": "https://self-hosted.example.com/api/0/",
    }
    with patch.dict("os.environ", env, clear=True):
        from context_providers.registry import build_registry

        registry = build_registry()

    sentry = [p for p in registry._providers if p.provider_type.value == "sentry"][0]
    assert isinstance(sentry, SentryProvider)
    assert sentry._base_url == "https://self-hosted.example.com/api/0"
