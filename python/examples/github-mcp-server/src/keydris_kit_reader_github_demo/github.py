"""Spending the released credential on the one call it authorized."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel

from keydris_kit_reader import KitTarget, apply_credentials
from keydris_kit_reader.mcp import KitSpend
from keydris_kit_reader_github_demo.config import config


# Annotating the handler with this model is what gives the tool an output schema
# and a filled `structuredContent`; the docstring is published as its description.
class GitHubUser(BaseModel):
    """The GitHub account a released personal access token belongs to."""

    login: str
    name: str | None
    html_url: str
    public_repos: int


class GitHubError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"GitHub replied {status}")
        self.status = status


class RedemptionRefused(Exception):
    """No credential arrived; the message is the gateway's readable problem."""


async def fetch_authenticated_user(spend: KitSpend) -> GitHubUser:
    """`GET /user` — the endpoint that answers "whose token is this?", which makes
    it the clearest proof that the credential the gateway released is the PAT and
    that it arrived intact.

    One tool call, one outbound request: the spend redeems this call's token for
    the credential this exact request needs — named by its downstream target
    (hostname without port, path without query) — at the moment the request is
    made. The secret never appears in tool code.
    """
    url = f"{config.github_api_base.rstrip('/')}/user"
    parts = urlsplit(url)
    target: KitTarget = {"host": parts.hostname or "", "path": parts.path or "/", "method": "GET"}

    redemption = await spend(target)
    if not redemption.ok:
        raise RedemptionRefused(redemption.problem)

    headers = {
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "keydris-mcp-demo",
    }
    url = apply_credentials(redemption.credentials, url, headers)

    async with httpx2.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code >= 400:
        raise GitHubError(response.status_code)
    return GitHubUser.model_validate(response.json())
