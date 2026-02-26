import logging
import re

import requests

from context_providers.interface import ContextProviderReference, ProviderType
from context_providers.jira_auth import JiraAuth

logger = logging.getLogger("app.jira_provider")

JIRA_URL_PATTERN = re.compile(
    r"https?://[^\s)]+?/(?:browse/|[^\s)]*?selectedIssue=|jira/[\w-]+/projects/[A-Z0-9_]+/issues/)([A-Z][A-Z0-9_]+-\d+)"
)

API_TIMEOUT = 1

ISSUE_FIELDS = "summary,status,priority,assignee,reporter,description,comment,issuetype,created,updated"


class JiraProvider:
    provider_type = ProviderType.JIRA

    def __init__(self, base_url: str, auth: JiraAuth):
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        auth.apply(self._session)

    def extract(self, text: str) -> list[ContextProviderReference]:
        keys = list(dict.fromkeys(JIRA_URL_PATTERN.findall(text)))
        if keys:
            logger.info(f"Extracted {len(keys)} Jira issue key(s): {keys}")
        return [ContextProviderReference(key) for key in keys]

    def resolve(self, reference: ContextProviderReference) -> str:
        key = reference
        url = f"{self._base_url}/rest/api/3/issue/{key}?fields={ISSUE_FIELDS}"
        try:
            resp = self._session.get(url, timeout=API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning(f"Failed to fetch Jira issue {key}", exc_info=True)
            return f"## Jira {key}\n\n*Could not fetch issue details.*"

        return self._format(key, data)

    def _format(self, key: str, data: dict) -> str:
        fields = data.get("fields", {})

        summary = fields.get("summary", "Unknown")
        issue_type = (fields.get("issuetype") or {}).get("name", "Unknown")
        status = (fields.get("status") or {}).get("name", "Unknown")
        priority = (fields.get("priority") or {}).get("name", "Unknown")
        assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
        reporter = (fields.get("reporter") or {}).get("displayName", "Unknown")
        created = fields.get("created", "N/A")
        updated = fields.get("updated", "N/A")

        lines = [f"## Jira {key}: {summary}"]
        lines.append("")
        lines.append(f"**Type:** {issue_type}")
        lines.append(f"**Status:** {status}")
        lines.append(f"**Priority:** {priority}")
        lines.append(f"**Assignee:** {assignee}")
        lines.append(f"**Reporter:** {reporter}")
        lines.append(f"**Created:** {created}")
        lines.append(f"**Updated:** {updated}")

        # Description
        raw_desc = fields.get("description")
        if raw_desc:
            if isinstance(raw_desc, str):
                desc_text = raw_desc
            else:
                desc_text = self._adf_to_text(raw_desc)
            if len(desc_text) > 1000:
                desc_text = desc_text[:1000] + "..."
            lines.append("")
            lines.append("**Description:**")
            lines.append(desc_text)

        # Comments (last 3)
        comment_data = fields.get("comment", {})
        comments = comment_data.get("comments", [])
        if comments:
            last_comments = comments[-3:]
            lines.append("")
            lines.append(f"**Comments** (last {len(last_comments)}):")
            for c in last_comments:
                author = (c.get("author") or {}).get("displayName", "Unknown")
                created_at = c.get("created", "")
                if created_at:
                    created_at = created_at[:10]
                body = c.get("body")
                if body:
                    if isinstance(body, str):
                        body_text = body
                    else:
                        body_text = self._adf_to_text(body)
                else:
                    body_text = ""
                if len(body_text) > 500:
                    body_text = body_text[:500] + "..."
                lines.append(f"- **{author}** ({created_at}): {body_text}")

        return "\n".join(lines)

    def _adf_to_text(self, node: dict) -> str:
        try:
            if not isinstance(node, dict):
                return str(node)

            if node.get("type") == "text":
                return node.get("text", "")

            parts = []
            for child in node.get("content", []):
                parts.append(self._adf_to_text(child))

            return "".join(parts)
        except Exception:
            logger.debug("Failed to convert ADF to text", exc_info=True)
            return "(unable to parse description)"
