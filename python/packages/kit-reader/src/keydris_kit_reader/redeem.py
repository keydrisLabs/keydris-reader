"""Turning the token an MCP request carried into a credential."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from keydris_kit_reader.token import calls_a_tool, kit_action_token_from, token_from
from keydris_kit_reader.transport import GatewayReply, Transport, urllib_transport
from keydris_kit_reader.types import KitActionContext, Redemption, Refused, Released

__all__ = ["KitReader"]

_JSON = {"content-type": "application/json"}


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
    ) -> None:
        """
        Args:
            gateway_url: The control plane's redemption endpoint, e.g.
                `https://api.keydris.com/gateway/credentials`.
            token_header: Legacy `/agent/authorize` header accepted as a
                fallback, lowercased. `mcp_kit_reader` requests carry their
                action-scoped token in MCP `params._meta` instead.
            transport: Injectable, for tests and for servers that route egress
                through their own client. Defaults to a stdlib `urllib` send.
            timeout: Seconds the default transport waits on the gateway.
        """
        scheme = urlsplit(gateway_url).scheme
        if scheme not in ("http", "https"):
            # Redemption posts a live token; `urlopen` would just as happily
            # honour `file:` or `ftp:` and send it somewhere it cannot be spent.
            raise ValueError(f"gateway_url must be an http(s) URL, got {gateway_url!r}")

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

    async def redeem(self, body: object, *, header: str | None = None) -> Redemption | None:
        """Turns the token carried by an MCP request into the credentials the
        server needs upstream.

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

        return await self._exchange(token, kit_action_token.context)

    async def _exchange(self, token: str, context: KitActionContext | None) -> Redemption:
        payload: dict[str, Any] = {"token": token}
        if context is not None:
            payload.update(context)

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

        return Released(credentials=tuple(credentials))


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
