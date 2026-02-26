import logging
import re

import requests

from context_providers.interface import ContextProviderReference, ProviderType

logger = logging.getLogger("app.sentry_provider")

# Matches: https://{org}.sentry.io/issues/{id}/  and  https://sentry.io/organizations/{org}/issues/{id}/
SENTRY_URL_PATTERN = re.compile(
    r"https://(?:[\w-]+\.sentry\.io/issues/|sentry\.io/organizations/[\w-]+/issues/)(\d+)"
)

API_TIMEOUT = 1


class SentryProvider:
    provider_type = ProviderType.SENTRY

    def __init__(self, auth_token: str, base_url: str = "https://sentry.io/api/0/"):
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {auth_token}"

    def extract(self, text: str) -> list[ContextProviderReference]:
        ids = list(dict.fromkeys(SENTRY_URL_PATTERN.findall(text)))
        if ids:
            logger.info(f"Extracted {len(ids)} Sentry issue ID(s): {ids}")
        return [ContextProviderReference(issue_id) for issue_id in ids]

    def resolve(self, reference: ContextProviderReference) -> str:
        issue_id = reference
        issue = self._fetch_issue(issue_id)
        if not issue:
            return f"## Sentry Issue {issue_id}\n\n*Could not fetch issue details.*"

        event = self._fetch_latest_event(issue_id)
        return self._format(issue_id, issue, event)

    def _fetch_issue(self, issue_id: str) -> dict | None:
        url = f"{self._base_url}/issues/{issue_id}/"
        try:
            resp = self._session.get(url, timeout=API_TIMEOUT)
            self._log_rate_limit(resp)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning(f"Failed to fetch Sentry issue {issue_id}", exc_info=True)
            return None

    def _fetch_latest_event(self, issue_id: str) -> dict | None:
        url = f"{self._base_url}/issues/{issue_id}/events/latest/"
        try:
            resp = self._session.get(url, timeout=API_TIMEOUT)
            self._log_rate_limit(resp)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning(f"Failed to fetch latest event for issue {issue_id}", exc_info=True)
            return None

    def _log_rate_limit(self, resp: requests.Response) -> None:
        remaining = resp.headers.get("X-Sentry-Rate-Limit-Remaining")
        if remaining is not None:
            logger.debug(f"Sentry rate limit remaining: {remaining}")

    def _format(self, issue_id: str, issue: dict, event: dict | None) -> str:
        lines = [f"## Sentry Issue {issue_id}"]
        lines.append("")

        # Issue metadata
        lines.append(f"**Title:** {issue.get('title', 'Unknown')}")
        lines.append(f"**Status:** {issue.get('status', 'unknown')}")
        lines.append(f"**First seen:** {issue.get('firstSeen', 'N/A')}")
        lines.append(f"**Last seen:** {issue.get('lastSeen', 'N/A')}")
        lines.append(f"**Event count:** {issue.get('count', 'N/A')}")

        # Tags
        tags = issue.get("tags", [])
        if tags:
            tag_strs = [f"`{t.get('key', '?')}={t.get('value', '?')}`" for t in tags[:10]]
            lines.append(f"**Tags:** {', '.join(tag_strs)}")

        if not event:
            lines.append("")
            lines.append("*Could not fetch latest event details.*")
            return "\n".join(lines)

        lines.append("")

        # Exception info
        for entry in event.get("entries", []):
            if entry.get("type") == "exception":
                for exc_val in entry.get("data", {}).get("values", []):
                    exc_type = exc_val.get("type", "Exception")
                    exc_value = exc_val.get("value", "")
                    lines.append(f"**Exception:** `{exc_type}: {exc_value}`")
                    lines.append("")

                    # Stacktrace (last 10 frames)
                    frames = exc_val.get("stacktrace", {}).get("frames", [])
                    if frames:
                        lines.append("**Stacktrace** (last 10 frames):")
                        lines.append("```")
                        for frame in frames[-10:]:
                            filename = frame.get("filename", "?")
                            lineno = frame.get("lineNo", "?")
                            func = frame.get("function", "?")
                            context_line = frame.get("context_line", "").strip()
                            lines.append(f"  {filename}:{lineno} in {func}")
                            if context_line:
                                lines.append(f"    {context_line}")
                        lines.append("```")
                        lines.append("")

            # Breadcrumbs (last 5)
            if entry.get("type") == "breadcrumbs":
                crumbs = entry.get("data", {}).get("values", [])
                if crumbs:
                    lines.append("**Breadcrumbs** (last 5):")
                    for crumb in crumbs[-5:]:
                        category = crumb.get("category", "")
                        message = crumb.get("message", "")
                        level = crumb.get("level", "")
                        timestamp = crumb.get("timestamp", "")
                        lines.append(f"- [{level}] {category}: {message} ({timestamp})")
                    lines.append("")

            # Request data
            if entry.get("type") == "request":
                req = entry.get("data", {})
                method = req.get("method", "")
                url = req.get("url", "")
                if method or url:
                    lines.append(f"**Request:** `{method} {url}`")
                    lines.append("")

        return "\n".join(lines)
