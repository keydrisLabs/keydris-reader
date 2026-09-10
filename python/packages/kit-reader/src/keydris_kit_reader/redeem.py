"""Turning the token an MCP request carried into a credential."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from keydris_kit_reader.token import calls_a_tool, kit_action_token_from, token_from
from keydris_kit_reader.transport import GatewayReply, Transport, urllib_transport
from keydris_kit_reader.types import (
    KitActionContext,
    KitTarget,
    Redemption,
    Refused,
    Released,
)

__all__ = ["KitReader"]

_JSON = {"content-type": "application/json"}

_LOOPBACK_V4 = re.compile(r"^127(\.\d{1,3}){3}$")


def _is_loopback_host(hostname: str) -> bool:
    """Loopback never leaves the machine, so plaintext is acceptable there — and only there."""
    return hostname == "localhost" or hostname == "::1" or bool(_LOOPBACK_V4.match(hostname))


class KitReader:
    """A reader bound to one gateway.

    Construct it once at startup and hand it each MCP request; it holds no
    per-request state, so a single instance serves every connection.
    """

    def __init__(
        self,
        *,
        gateway_url: str,
        token_header: str = "authorization",
        transport: Transport | None = None,
        timeout: float = 10.0,
        allow_insecure_gateway_url: bool = False,
    ) -> None:
        """
        Args:
            gateway_url: The control plane's redemption endpoint, e.g.
                `https://api.keydris.com/gateway/credentials`. Must be `https`
                unless the host is loopback: redemption posts a live token and
                receives a raw secret, and neither belongs on a plaintext
                network hop.
            token_header: Legacy `/agent/authorize` header accepted as a
                fallback, lowercased. `mcp_kit_reader` requests carry their
                action-scoped token in MCP `params._meta` instead.
            transport: Injectable, for tests and for servers that route egress
                through their own client. Defaults to a stdlib `urllib` send.
            timeout: Seconds the default transport waits on the gateway.
            allow_insecure_gateway_url: Permit a non-loopback `http` gateway
                URL. A lab-only escape hatch — a constructor argument rather
                than an environment variable so the decision is visible in code
                review, not buried in deployment config.
        """
        parts = urlsplit(gateway_url)
        if parts.scheme not in ("http", "https"):
            # Redemption posts a live token; `urlopen` would just as happily
            # honour `file:` or `ftp:` and send it somewhere it cannot be spent.
            raise ValueError(f"gateway_url must be an http(s) URL, got {gateway_url!r}")
        if (
            parts.scheme == "http"
            and not _is_loopback_host(parts.hostname or "")
            and not allow_insecure_gateway_url
        ):
            # Fails at construction, not at redeem time: a misconfigured gateway
            # URL should surface as one clear error at boot, not as a per-call
            # refusal the agent sees.
            raise ValueError(
                f"gateway_url {gateway_url!r} is plaintext http to a non-loopback host: "
                "the redemption channel carries a live token and returns a raw secret. "
                "Use https, or pass allow_insecure_gateway_url=True for a lab setup."
            )

        self._gateway_url = gateway_url
        self._token_header = token_header.strip().lower()
        self._transport = transport if transport is not None else urllib_transport(timeout)

    @property
    def token_header(self) -> str:
        """The header this reader falls back to, lowercased."""
        return self._token_header

    def calls_a_tool(self, body: object) -> bool:
        """Whether this JSON-RPC body invokes a tool — i.e. whether it would
        cost a secret."""
        return calls_a_tool(body)

    async def redeem(
        self,
        body: object,
        *,
        header: str | None = None,
        target: KitTarget | None = None,
    ) -> Redemption | None:
        """Turns the token carried by an MCP request into the credentials the
        server needs upstream.

        `target` names the downstream request the credential is for; the gateway
        requires it for every KIT redemption, so call this at the moment the
        outbound request is known, not before.

        Only `tools/call` is touched. Every redemption reveals a secret from the
        vault, and `initialize`/`tools/list` disclose nothing that would justify
        one — so a client with no token at all can still connect and see what is
        on offer, and finds out it needs one only when it asks for something
        that costs a secret. For those, this returns `None`.

        Otherwise it returns a `Redemption`: success, or a readable problem. It
        does not raise.
        """
        if not calls_a_tool(body):
            return None

        kit_action_token = kit_action_token_from(body)
        if kit_action_token.problem:
            return Refused(problem=kit_action_token.problem)

        header_token = token_from(header)
        if kit_action_token.token and header_token and kit_action_token.token != header_token:
            return Refused(
                problem="The MCP request contains conflicting Keydris action and header tokens."
            )

        token = kit_action_token.token or header_token
        if not token:
            return Refused(
                problem=(
                    'No Keydris KIT action token in params._meta["keydris/kit_action_token"] '
                    f"or on the {self._token_header} header, so there is nothing to "
                    "exchange for a credential."
                )
            )

        return await self._exchange(token, kit_action_token.context, target)

    async def _exchange(
        self, token: str, context: KitActionContext | None, target: KitTarget | None
    ) -> Redemption:
        # The gateway's schema pairs them strictly: a KIT action token must
        # arrive with both the MCP action and the downstream target, a legacy
        # header token with neither. A tokenized call without a target is
        # refused here, with a hint at the fix, instead of as an opaque
        # validation error from the wire.
        if context is not None and target is None:
            return Refused(
                problem=(
                    "A KIT action token redemption needs the downstream target "
                    "(host, path, method) of the request it authorizes."
                )
            )

        payload: dict[str, Any] = {"token": token}
        if context is not None and target is not None:
            payload.update(context)
            payload["target"] = target

        try:
            reply = await self._transport(
                self._gateway_url, headers=_JSON, body=json.dumps(payload).encode()
            )
        except Exception:
            # Whatever the transport raised — a refused connection, a timeout, a
            # DNS failure — the agent needs the same one-line answer, not a
            # traceback from inside a tool call.
            return Refused(problem="The Keydris gateway could not be reached.")

        document = _json_or_none(reply)
        if not 200 <= reply.status < 300:
            return Refused(problem=f"The Keydris gateway refused: {_code(document, reply)}.")

        credentials = document.get("credentials") if isinstance(document, Mapping) else None
        if not isinstance(credentials, list) or not credentials:
            return Refused(problem="The Keydris gateway released nothing.")
        if not all(_is_credential_envelope(item) for item in credentials):
            return Refused(
                problem=(
                    "The Keydris gateway returned a credential in a shape "
                    "this reader does not recognize."
                )
            )

        return Released(credentials=tuple(credentials))


def _is_credential_envelope(value: object) -> bool:
    """Accepts only the exact envelope shape the gateway publishes.

    Whatever the gateway (or something impersonating it) returns is about to be
    applied to an outbound request as a header or query parameter — an
    unrecognized shape is refused rather than coerced.
    """
    if not isinstance(value, Mapping):
        return False
    return (
        value.get("type") in ("header", "query")
        and isinstance(value.get("name"), str)
        and bool(value.get("name"))
        and isinstance(value.get("prefix"), str)
        and isinstance(value.get("value"), str)
    )


def _json_or_none(reply: GatewayReply) -> Any:
    try:
        return json.loads(reply.body)
    except ValueError:
        return None


def _code(document: Any, reply: GatewayReply) -> str:
    """The code the gateway named, or the status it refused with."""
    if isinstance(document, Mapping):
        error = document.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            if isinstance(code, str) and code:
                return code
    return f"HTTP {reply.status}"
