from typing import Protocol

import requests


class JiraAuth(Protocol):
    def apply(self, session: requests.Session) -> None: ...


class BasicJiraAuth:
    def __init__(self, email: str, api_token: str):
        self._email = email
        self._api_token = api_token

    def apply(self, session: requests.Session) -> None:
        session.auth = (self._email, self._api_token)
