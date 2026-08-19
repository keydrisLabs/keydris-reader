"""Middleware for the MCP Python SDK.

Optional: import it only if you serve with `mcp`, which is what the
`keydris-kit-reader[mcp]` extra installs. Nothing here is imported at runtime by
the rest of the library, and nothing here imports `mcp` at runtime either.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from keydris_kit_reader.redeem import KitReader
from keydris_kit_reader.types import Redemption

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext

__all__ = ["current_redemption", "keydris_credentials"]

_redemption: ContextVar[Redemption | None] = ContextVar("keydris_redemption", default=None)


def current_redemption() -> Redemption | None:
    """This request's redemption, inside a tool handler.

    `None` when the request calls no tool, or when `keydris_credentials` is not
    installed. A refusal is a `Refused`, not a `None`: report its `problem`.
    """
    return _redemption.get()


def keydris_credentials(reader: KitReader) -> ServerMiddleware[Any]:
    """Turns the token the proxy injected into the credential this server needs
    upstream, and leaves the result on `current_redemption()`.

    Register it on the server, once, at startup:

        mcp = MCPServer("your-server", middleware=[keydris_credentials(reader)])

    Requests that call no tool pass through untouched: `initialize` and
    `tools/list` cost nothing, so a client with no token can still connect and
    see what is on offer. Everything that stops a credential arriving lands as a
    `Refused` for the tool handler to report, rather than as a transport failure
    the agent cannot read.

    The redemption is reset when the call returns, so the released secret is
    reachable only from inside the request it was authorized for — the thing a
    server otherwise has to be careful about for itself.
    """

    async def middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)

        # The raw params this middleware tier sees are the JSON-RPC ones, `_meta`
        # included; `ctx.request` is the HTTP request, absent on stdio.
        headers = getattr(ctx.request, "headers", None)
        header = headers.get(reader.token_header) if isinstance(headers, Mapping) else None
        redemption = await reader.redeem(
            {"method": ctx.method, "params": ctx.params}, header=header
        )

        restore = _redemption.set(redemption)
        try:
            return await call_next(ctx)
        finally:
            _redemption.reset(restore)

    return middleware
