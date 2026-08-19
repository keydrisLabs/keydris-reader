"""The wire shapes the gateway speaks and the results a redemption can have."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

__all__ = [
    "CredentialEnvelope",
    "KitActionContext",
    "McpActionCall",
    "Redemption",
    "Refused",
    "Released",
    "TokenLookup",
]


class CredentialEnvelope(TypedDict):
    """Mirrors the gateway's `credentialEnvelopeSchema`."""

    type: Literal["header", "query"]
    name: str
    prefix: str
    value: str


class McpActionCall(TypedDict):
    """The tool call a KIT action token was minted for."""

    method: Literal["tools/call"]
    action_name: str
    parameters: dict[str, Any]


class KitActionContext(TypedDict):
    """Sent alongside the token so the gateway evaluates policy against the
    action that is really about to happen."""

    mcp: McpActionCall


@dataclass(frozen=True, slots=True, repr=False)
class Released:
    """Credentials the gateway released for one call.

    The repr is redacted rather than generated: a released envelope holds a live
    secret, and the default dataclass repr would put it in every traceback,
    `print`, and structured log line that happened to touch this object.
    """

    credentials: tuple[CredentialEnvelope, ...]
    ok: Literal[True] = True

    def __repr__(self) -> str:
        return f"Released(credentials=<{len(self.credentials)} redacted>)"


@dataclass(frozen=True, slots=True)
class Refused:
    """Why no credential arrived, in words meant for the agent to read."""

    problem: str
    ok: Literal[False] = False


Redemption = Released | Refused
"""A redemption never raises: anything that stops a credential arriving is
something the agent should be told about in the tool result, not an exception
that leaves it guessing. `Refused.problem` is that explanation.

Both arms carry a literal `ok`, so a type checker narrows the union on it just
as `if (redemption.ok)` narrows in TypeScript."""


@dataclass(frozen=True, slots=True)
class TokenLookup:
    """What `kit_action_token_from` found in a JSON-RPC body."""

    token: str | None = None
    context: KitActionContext | None = None
    problem: str | None = None
