"""Reading the action-scoped token out of an MCP request."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from keydris_kit_reader.types import TokenLookup

__all__ = [
    "KIT_ACTION_TOKEN_META_KEY",
    "calls_a_tool",
    "kit_action_token_from",
    "token_from",
]

KIT_ACTION_TOKEN_META_KEY = "keydris/kit_action_token"
"""The MCP `params._meta` key an `mcp_kit_reader` proxy injects the token on."""

_BEARER = re.compile(r"^bearer\s+", re.IGNORECASE)


def token_from(raw: str | None) -> str | None:
    """Accepts both `Bearer <jwt>` and a bare token, since the header the proxy
    uses is configurable and only the default carries a scheme."""
    value = raw.strip() if raw is not None else ""
    if not value:
        return None
    return _BEARER.sub("", value, count=1)


def _messages(body: object) -> list[Any]:
    """One JSON-RPC message or a batch, read the same way."""
    return list(body) if isinstance(body, list) else [body]


def kit_action_token_from(body: object) -> TokenLookup:
    """Reads the action-scoped token injected by an `mcp_kit_reader` proxy and
    the exact tool arguments it authorized. Batched tokenized actions are
    refused: one KIT action token can be redeemed for one action only.
    """
    lookup = TokenLookup()

    for message in _messages(body):
        if not isinstance(message, Mapping) or message.get("method") != "tools/call":
            continue
        params = message.get("params")
        if not isinstance(params, Mapping):
            continue
        meta = params.get("_meta")
        if not isinstance(meta, Mapping) or KIT_ACTION_TOKEN_META_KEY not in meta:
            continue

        raw = meta[KIT_ACTION_TOKEN_META_KEY]
        token = token_from(raw) if isinstance(raw, str) else None
        if not token:
            return TokenLookup(problem="The Keydris KIT action token is malformed.")
        if lookup.token:
            return TokenLookup(
                problem="A KIT action token can authorize only one MCP action per request."
            )

        name = params.get("name")
        arguments = params.get("arguments")
        if (
            not isinstance(name, str)
            or not name
            or (arguments is not None and not isinstance(arguments, Mapping))
        ):
            return TokenLookup(problem="The tokenized MCP tool call is malformed.")

        lookup = TokenLookup(
            token=token,
            context={
                "mcp": {
                    "method": "tools/call",
                    "action_name": name,
                    "parameters": dict(arguments or {}),
                }
            },
        )

    return lookup


def calls_a_tool(body: object) -> bool:
    """Whether the JSON-RPC body — one message or a batch — invokes a tool."""
    return any(
        isinstance(message, Mapping) and message.get("method") == "tools/call"
        for message in _messages(body)
    )
