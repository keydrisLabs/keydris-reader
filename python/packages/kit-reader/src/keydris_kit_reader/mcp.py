"""Middleware for the MCP Python SDK.

Optional: import it only if you serve with `mcp`, which is what the
`keydris-kit-reader[mcp]` extra installs. Nothing here is imported at runtime by
the rest of the library, and nothing here imports `mcp` at runtime either.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from keydris_kit_reader.redeem import KitReader
from keydris_kit_reader.types import KitTarget, Redemption, Refused

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext

__all__ = ["KitSpend", "current_spend", "keydris_credentials"]

KitSpend = Callable[[KitTarget], Awaitable[Redemption]]
"""One request's chance to redeem. Callable once: the gateway consumes the token
atomically on release, so a second call is refused locally with a readable
problem instead of a wire round-trip that cannot succeed."""

_spend: ContextVar[KitSpend | None] = ContextVar("keydris_kit_spend", default=None)


async def _not_armed(_target: KitTarget) -> Redemption:
    return Refused(
        problem="The Keydris kit reader middleware is not armed for this request."
    )


def current_spend() -> KitSpend:
    """The one-shot spend `keydris_credentials` armed for the current tool call.

    Never `None`: when the middleware is not registered (or the code runs
    outside a `tools/call`) the returned spend refuses with a readable problem
    instead of crashing. Call it with the downstream target — host, path,
    method — of the one outbound request the credential is for.
    """
    return _spend.get() or _not_armed


def keydris_credentials(reader: KitReader) -> ServerMiddleware[Any]:
    """Arms each `tools/call` with a one-shot spend of the token the proxy
    injected, reachable from tool handlers via `current_spend()`.

    The gateway redeems a KIT action token only together with the downstream
    target (host, path, method) of the request it authorizes — which is known
    inside the tool at request time, not when the MCP request arrives. So this
    middleware does not redeem: the tool spends when it makes its one outbound
    request, and the released secret is reachable only from inside the call it
    was authorized for.

    Register it on the server, once, at startup:

        mcp = MCPServer("your-server", middleware=[keydris_credentials(reader)])

    Requests that call no tool pass through untouched: `initialize` and
    `tools/list` cost nothing, so a client with no token can still connect and
    see what is on offer. Everything that stops a credential arriving lands as a
    `Refused` for the tool handler to report, rather than as a transport failure
    the agent cannot read.
    """

    async def middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)

        # The raw params this middleware tier sees are the JSON-RPC ones, `_meta`
        # included; `ctx.request` is the HTTP request, absent on stdio.
        headers = getattr(ctx.request, "headers", None)
        header = headers.get(reader.token_header) if isinstance(headers, Mapping) else None
        body = {"method": ctx.method, "params": ctx.params}

        spent = False

        async def spend(target: KitTarget) -> Redemption:
            nonlocal spent
            if spent:
                return Refused(
                    problem=(
                        "The KIT action token for this request was already spent: "
                        "one token authorizes one outbound call."
                    )
                )
            spent = True
            redemption = await reader.redeem(body, header=header, target=target)
            if redemption is None:
                return Refused(
                    problem=(
                        "This MCP request calls no tool, so there is no action "
                        "token to redeem."
                    )
                )
            return redemption

        restore = _spend.set(spend)
        try:
            return await call_next(ctx)
        finally:
            _spend.reset(restore)

    return middleware
