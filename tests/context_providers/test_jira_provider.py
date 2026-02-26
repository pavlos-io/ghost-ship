from unittest.mock import MagicMock, patch

from context_providers.interface import ContextProviderReference
from context_providers.jira_auth import BasicJiraAuth
from context_providers.jira_provider import JIRA_URL_PATTERN, JiraProvider


# ── URL pattern extraction ──────────────────────────────────────────


def test_pattern_browse_url():
    m = JIRA_URL_PATTERN.search("https://myorg.atlassian.net/browse/PROJ-123")
    assert m and m.group(1) == "PROJ-123"


def test_pattern_board_selected_issue():
    m = JIRA_URL_PATTERN.search(
        "https://myorg.atlassian.net/jira/software/boards/1?selectedIssue=DATA-42"
    )
    assert m and m.group(1) == "DATA-42"


def test_pattern_next_gen_issues():
    m = JIRA_URL_PATTERN.search(
        "https://myorg.atlassian.net/jira/software/projects/PROJ/issues/PROJ-456"
    )
    assert m and m.group(1) == "PROJ-456"


def test_pattern_no_match_on_plain_text():
    m = JIRA_URL_PATTERN.search("this is just PROJ-123 without a URL")
    assert m is None


def test_pattern_extracts_from_surrounding_text():
    text = "Check this out https://acme.atlassian.net/browse/BUG-99 please"
    m = JIRA_URL_PATTERN.search(text)
    assert m and m.group(1) == "BUG-99"


# ── extract() ───────────────────────────────────────────────────────


def _make_provider() -> JiraProvider:
    auth = MagicMock()
    return JiraProvider("https://test.atlassian.net", auth)


def test_extract_deduplicates():
    provider = _make_provider()
    text = (
        "https://test.atlassian.net/browse/AB-1 "
        "https://test.atlassian.net/browse/AB-1 "
        "https://test.atlassian.net/browse/CD-2"
    )
    refs = provider.extract(text)
    assert [str(r) for r in refs] == ["AB-1", "CD-2"]


def test_extract_returns_empty_for_no_urls():
    provider = _make_provider()
    assert provider.extract("nothing here") == []


# ── resolve() ───────────────────────────────────────────────────────


SAMPLE_ISSUE = {
    "fields": {
        "summary": "Login page throws 500",
        "issuetype": {"name": "Bug"},
        "status": {"name": "In Progress"},
        "priority": {"name": "High"},
        "assignee": {"displayName": "Alice Smith"},
        "reporter": {"displayName": "Bob Jones"},
        "created": "2025-01-15T10:30:00.000+0000",
        "updated": "2025-01-16T14:22:00.000+0000",
        "description": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Login page returns HTTP 500 when submitting."}],
                }
            ],
        },
        "comment": {
            "comments": [
                {
                    "author": {"displayName": "Charlie"},
                    "created": "2025-01-15T08:00:00.000+0000",
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "I can reproduce this on staging."}],
                            }
                        ],
                    },
                },
                {
                    "author": {"displayName": "Alice"},
                    "created": "2025-01-16T12:00:00.000+0000",
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Root cause identified."}],
                            }
                        ],
                    },
                },
            ]
        },
    }
}


def test_resolve_success():
    provider = _make_provider()
    mock_resp = MagicMock()
    mock_resp.json.return_value = SAMPLE_ISSUE
    mock_resp.raise_for_status = MagicMock()
    provider._session.get = MagicMock(return_value=mock_resp)

    result = provider.resolve(ContextProviderReference("PROJ-123"))

    assert "## Jira PROJ-123: Login page throws 500" in result
    assert "**Type:** Bug" in result
    assert "**Status:** In Progress" in result
    assert "**Priority:** High" in result
    assert "**Assignee:** Alice Smith" in result
    assert "**Reporter:** Bob Jones" in result
    assert "Login page returns HTTP 500" in result
    assert "**Charlie**" in result
    assert "Root cause identified." in result


def test_resolve_api_failure():
    provider = _make_provider()
    provider._session.get = MagicMock(side_effect=Exception("timeout"))

    result = provider.resolve(ContextProviderReference("PROJ-123"))

    assert "Could not fetch issue details" in result


def test_resolve_missing_fields():
    """Missing optional fields should not crash."""
    provider = _make_provider()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"fields": {}}
    mock_resp.raise_for_status = MagicMock()
    provider._session.get = MagicMock(return_value=mock_resp)

    result = provider.resolve(ContextProviderReference("PROJ-1"))

    assert "## Jira PROJ-1: Unknown" in result
    assert "**Status:** Unknown" in result
    assert "**Assignee:** Unassigned" in result


def test_resolve_string_description():
    """API v2 / self-hosted may return description as plain string."""
    provider = _make_provider()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "fields": {
            "summary": "Test",
            "description": "Plain text description",
            "comment": {"comments": []},
        }
    }
    mock_resp.raise_for_status = MagicMock()
    provider._session.get = MagicMock(return_value=mock_resp)

    result = provider.resolve(ContextProviderReference("TEST-1"))

    assert "Plain text description" in result


def test_resolve_truncates_long_description():
    provider = _make_provider()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "fields": {
            "summary": "Test",
            "description": "x" * 2000,
            "comment": {"comments": []},
        }
    }
    mock_resp.raise_for_status = MagicMock()
    provider._session.get = MagicMock(return_value=mock_resp)

    result = provider.resolve(ContextProviderReference("TEST-1"))

    assert "x" * 1000 + "..." in result
    assert "x" * 1001 not in result


def test_resolve_limits_to_last_3_comments():
    comments = [
        {
            "author": {"displayName": f"User{i}"},
            "created": f"2025-01-{10+i:02d}T00:00:00.000+0000",
            "body": f"Comment {i}",
        }
        for i in range(5)
    ]
    provider = _make_provider()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "fields": {
            "summary": "Test",
            "comment": {"comments": comments},
        }
    }
    mock_resp.raise_for_status = MagicMock()
    provider._session.get = MagicMock(return_value=mock_resp)

    result = provider.resolve(ContextProviderReference("TEST-1"))

    assert "User0" not in result
    assert "User1" not in result
    assert "User2" in result
    assert "User3" in result
    assert "User4" in result


# ── BasicJiraAuth ───────────────────────────────────────────────────


def test_basic_auth_applies_credentials():
    auth = BasicJiraAuth("user@example.com", "token123")
    session = MagicMock()
    auth.apply(session)
    assert session.auth == ("user@example.com", "token123")


# ── build_registry ──────────────────────────────────────────────────


def test_registry_registers_jira_when_env_set():
    env = {
        "JIRA_BASE_URL": "https://test.atlassian.net",
        "JIRA_EMAIL": "a@b.com",
        "JIRA_API_TOKEN": "tok",
    }
    with patch.dict("os.environ", env, clear=False):
        from context_providers.registry import build_registry

        registry = build_registry()

    jira_providers = [
        p for p in registry._providers if p.provider_type.value == "jira"
    ]
    assert len(jira_providers) == 1


def test_registry_skips_jira_when_env_missing():
    env = {"JIRA_BASE_URL": "https://test.atlassian.net"}
    with patch.dict("os.environ", env, clear=True):
        from context_providers.registry import build_registry

        registry = build_registry()

    jira_providers = [
        p for p in registry._providers if p.provider_type.value == "jira"
    ]
    assert len(jira_providers) == 0
