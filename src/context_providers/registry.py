import logging
import os

from context_providers.interface import ContextProvider
from context_providers.jira_auth import BasicJiraAuth
from context_providers.jira_provider import JiraProvider
from context_providers.sentry_provider import SentryProvider

logger = logging.getLogger("app.context_registry")


class ContextProviderRegistry:
    def __init__(self):
        self._providers: list[ContextProvider] = []

    def register(self, provider: ContextProvider) -> None:
        logger.info(f"Registered context provider: {provider.provider_type.value}")
        self._providers.append(provider)

    def enrich(self, text: str) -> str:
        sections = []
        for provider in self._providers:
            try:
                refs = provider.extract(text)
                for ref in refs:
                    try:
                        section = provider.resolve(ref)
                        if section:
                            sections.append(section)
                    except Exception:
                        logger.warning(
                            f"Failed to resolve {ref} via {provider.provider_type.value}",
                            exc_info=True,
                        )
            except Exception:
                logger.warning(
                    f"Failed to extract from {provider.provider_type.value}",
                    exc_info=True,
                )

        if not sections:
            return ""

        return "\n---\n# External Context\n\n" + "\n\n".join(sections) + "\n"


def build_registry() -> ContextProviderRegistry:
    registry = ContextProviderRegistry()

    sentry_token = os.environ.get("SENTRY_AUTH_TOKEN")
    if sentry_token:
        base_url = os.environ.get("SENTRY_BASE_URL", "https://sentry.io/api/0/")
        registry.register(SentryProvider(auth_token=sentry_token, base_url=base_url))

    jira_base_url = os.environ.get("JIRA_BASE_URL")
    jira_email = os.environ.get("JIRA_EMAIL")
    jira_api_token = os.environ.get("JIRA_API_TOKEN")
    if jira_base_url and jira_email and jira_api_token:
        auth = BasicJiraAuth(jira_email, jira_api_token)
        registry.register(JiraProvider(jira_base_url, auth))

    return registry
