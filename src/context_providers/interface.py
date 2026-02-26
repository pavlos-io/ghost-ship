from enum import Enum
from typing import NewType, Protocol

ContextProviderReference = NewType("ContextProviderReference", str)


class ProviderType(Enum):
    SENTRY = "sentry"
    JIRA = "jira"


class ContextProvider(Protocol):
    @property
    def provider_type(self) -> ProviderType: ...
    def extract(self, text: str) -> list[ContextProviderReference]: ...
    def resolve(self, reference: ContextProviderReference) -> str: ...
