"""How the redemption POST leaves the process.

The library has no runtime dependencies, so the default transport is stdlib
`urllib`, run off the event loop. Anything async can be substituted — an
`httpx`/`httpx2` client, an instrumented one, a stub in a test — by passing
`transport=` to `KitReader`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

__all__ = ["GatewayReply", "Transport", "urllib_transport"]


@dataclass(frozen=True, slots=True)
class GatewayReply:
    """A status and a body: everything the reader needs to judge a redemption."""

    status: int
    body: bytes


class Transport(Protocol):
    """Posts one JSON body to the gateway and answers with its reply.

    Raising is how a transport says the gateway could not be reached; a refusal
    is a `GatewayReply` carrying the refusing status, not an exception.
    """

    async def __call__(
        self, url: str, *, headers: Mapping[str, str], body: bytes
    ) -> GatewayReply: ...


async def _in_thread(post: Callable[[], GatewayReply]) -> GatewayReply:
    """Runs the blocking send off the event loop.

    anyio covers both async backends and ships with every MCP install; falling
    back to `asyncio.to_thread` is what keeps this library dependency-free when
    it is absent.
    """
    try:
        from anyio import to_thread
    except ModuleNotFoundError:
        return await asyncio.to_thread(post)
    return await to_thread.run_sync(post)


def urllib_transport(timeout: float) -> Transport:
    """The default transport: a blocking `urlopen` moved off the event loop.

    `timeout` is not optional here the way it is for `fetch`: a stdlib send with
    no deadline can hang a tool call indefinitely, and a slow gateway should
    surface as a readable problem instead.
    """

    async def send(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        def post() -> GatewayReply:
            # `KitReader` has already rejected any scheme but http(s).
            request = Request(url, data=body, headers=dict(headers), method="POST")
            try:
                with urlopen(request, timeout=timeout) as response:
                    return GatewayReply(response.status, response.read())
            except HTTPError as refusal:
                # urllib raises on 4xx/5xx, but a refusal is an answer: its body
                # carries the code that names why, which the tool error quotes.
                with refusal:
                    return GatewayReply(refusal.code, refusal.read())

        return await _in_thread(post)

    return send
