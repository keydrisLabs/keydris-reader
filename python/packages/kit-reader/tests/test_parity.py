"""The two implementations have to say the same thing.

A `problem` is read by an agent, not a human, so the wording is part of the wire
contract: a server written in either language must be substitutable behind the
same policy. This checks the strings this reader actually produces against the
Node source they were taken from, rather than trusting that they were copied.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from keydris_kit_reader import GatewayReply, KitReader, Refused

NODE_SOURCE = Path(__file__).resolve().parents[4] / "node" / "packages" / "kit-reader" / "src"

HEADER = "x-keydris-token"
CODE = "policy_denied"


async def refuse(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
    return GatewayReply(403, b'{"error":{"code":"policy_denied"}}')


def tool_call(token: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"name": "github_whoami", "arguments": {}}
    if token:
        params["_meta"] = {"keydris/kit_action_token": token}
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


async def every_problem() -> list[str]:
    """One of each: the four the parser can report and the four the exchange can."""
    reader = KitReader(gateway_url="https://gateway.test/x", token_header=HEADER, transport=refuse)
    malformed = tool_call()
    malformed["params"]["_meta"] = {"keydris/kit_action_token": 42}
    unnamed = tool_call("action-token")
    unnamed["params"]["name"] = ""

    async def empty(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        return GatewayReply(200, b'{"credentials":[]}')

    async def unreachable(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        raise ConnectionRefusedError

    redemptions = [
        await reader.redeem(malformed),
        await reader.redeem([tool_call("t"), tool_call("t")]),
        await reader.redeem(unnamed),
        await reader.redeem(tool_call("action-token"), header="other-token"),
        await reader.redeem(tool_call()),
        await reader.redeem(tool_call("action-token")),
        await KitReader(gateway_url="https://gateway.test/x", transport=empty).redeem(
            tool_call("action-token")
        ),
        await KitReader(gateway_url="https://gateway.test/x", transport=unreachable).redeem(
            tool_call("action-token")
        ),
    ]
    problems = [r.problem for r in redemptions if isinstance(r, Refused)]
    assert len(problems) == len(redemptions), "every case here should refuse"
    return problems


@pytest.mark.skipif(not NODE_SOURCE.is_dir(), reason="the Node implementation is not checked out")
async def test_every_problem_this_reader_reports_is_the_node_wording() -> None:
    node = "\n".join(path.read_text() for path in NODE_SOURCE.glob("*.ts"))

    for problem in await every_problem():
        # The only two things that vary at runtime are the configured header name
        # and the code the gateway named; either side of them must match verbatim.
        for fragment in problem.replace(HEADER, "\x00").replace(CODE, "\x00").split("\x00"):
            assert fragment in node, f"Node says nothing like {fragment!r}"


async def test_the_meta_key_is_the_one_the_proxy_injects() -> None:
    from keydris_kit_reader import KIT_ACTION_TOKEN_META_KEY

    assert KIT_ACTION_TOKEN_META_KEY == "keydris/kit_action_token"
