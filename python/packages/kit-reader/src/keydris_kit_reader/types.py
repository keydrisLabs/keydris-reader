"""The wire shapes the gateway speaks and the results a redemption can have."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from keydris_kit_reader.telemetry import Outcome, ReaderTelemetry

__all__ = [
    "CredentialEnvelope",
    "KitActionContext",
    "KitTarget",
    "McpActionCall",
    "Redemption",
    "Refused",
    "Released",
    "TargetMethod",
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


TargetMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
"""HTTP methods the gateway's `target` schema accepts."""


class KitTarget(TypedDict):
    """The downstream request the credential is for.

    The gateway matches it against the vault's host/path patterns and evaluates
    policy against it, so it must name the request that is really about to
    leave — hostname without port, path without query string.
    """

    host: str
    path: str
    method: TargetMethod


@dataclass(frozen=True, slots=True, repr=False)
class Released:
    """Credentials the gateway released for one call.

    The repr is redacted rather than generated: a released envelope holds a live
    secret, and the default dataclass repr would put it in every traceback,
    `print`, and structured log line that happened to touch this object.
    """

    credentials: tuple[CredentialEnvelope, ...]
    ok: Literal[True] = True
    decision_id: str | None = None
    outcome_receipt: str | None = None
    telemetry: ReaderTelemetry | None = None

    def report_outcome(
        self, outcome: Outcome, *, provider_status: int | None = None, error_code: str | None = None
    ) -> None:
        if self.telemetry and self.outcome_receipt:
            self.telemetry.outcome(
                self.outcome_receipt,
                outcome,
                provider_status=provider_status,
                error_code=error_code,
            )

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
