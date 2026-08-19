"""Ports `node/packages/kit-reader/src/redeem.test.ts`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from keydris_kit_reader import CredentialEnvelope, GatewayReply, KitReader, Refused, Released

GATEWAY = "https://gateway.test/gateway/credentials"

RELEASED: list[CredentialEnvelope] = [
    {"type": "header", "name": "Authorization", "prefix": "", "value": "Bearer ghp_x"}
]


@dataclass
class GatewayStub:
    """Records what the gateway was sent and answers with a canned response."""

    status: int = 200
    body: Any = field(default_factory=dict)
    throws: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        self.calls.append({"url": url, "body": json.loads(body)})
        if self.throws:
            raise ConnectionRefusedError("connection refused")
        return GatewayReply(self.status, json.dumps(self.body).encode())


def reader_for(gateway: GatewayStub, **options: Any) -> KitReader:
    return KitReader(gateway_url=GATEWAY, transport=gateway, **options)


def tool_call(token: str | None = None, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"name": "github_whoami", "arguments": arguments or {}}
    if token:
        params["_meta"] = {"keydris/kit_action_token": token}
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


async def test_sends_the_token_with_the_call_it_authorizes() -> None:
    gateway = GatewayStub(body={"credentials": RELEASED})
    reader = reader_for(gateway)

    redemption = await reader.redeem(tool_call("action-token", {"verbose": True}))

    assert redemption == Released(credentials=tuple(RELEASED))
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["url"] == GATEWAY
    assert gateway.calls[0]["body"] == {
        "token": "action-token",
        "mcp": {
            "method": "tools/call",
            "action_name": "github_whoami",
            "parameters": {"verbose": True},
        },
    }


async def test_costs_nothing_for_initialize_and_tools_list() -> None:
    gateway = GatewayStub(body={"credentials": RELEASED})
    reader = reader_for(gateway)

    assert await reader.redeem({"method": "initialize"}) is None
    assert await reader.redeem({"method": "tools/list"}, header="Bearer t") is None
    assert gateway.calls == []


async def test_falls_back_to_the_configured_header_sending_the_token_alone() -> None:
    gateway = GatewayStub(body={"credentials": RELEASED})
    reader = reader_for(gateway, token_header="X-Keydris-Token")

    assert reader.token_header == "x-keydris-token"
    redemption = await reader.redeem(tool_call(), header="Bearer header-token")

    assert redemption == Released(credentials=tuple(RELEASED))
    assert gateway.calls[0]["body"] == {"token": "header-token"}


async def test_refuses_a_request_whose_action_and_header_tokens_disagree() -> None:
    gateway = GatewayStub(body={"credentials": RELEASED})
    reader = reader_for(gateway)

    redemption = await reader.redeem(tool_call("action-token"), header="other-token")

    assert redemption == Refused(
        problem="The MCP request contains conflicting Keydris action and header tokens."
    )
    assert gateway.calls == []


async def test_names_the_header_it_looked_on_when_no_token_arrived_at_all() -> None:
    gateway = GatewayStub(body={"credentials": RELEASED})
    reader = reader_for(gateway, token_header="x-keydris-token")

    redemption = await reader.redeem(tool_call())

    assert redemption == Refused(
        problem=(
            'No Keydris KIT action token in params._meta["keydris/kit_action_token"] or on the '
            "x-keydris-token header, so there is nothing to exchange for a credential."
        )
    )
    assert gateway.calls == []


async def test_passes_a_malformed_token_problem_through_without_calling_the_gateway() -> None:
    gateway = GatewayStub(body={"credentials": RELEASED})
    reader = reader_for(gateway)

    redemption = await reader.redeem([tool_call("action-token"), tool_call("action-token")])

    assert redemption == Refused(
        problem="A KIT action token can authorize only one MCP action per request."
    )
    assert gateway.calls == []


async def test_reports_a_refusal_by_the_code_the_gateway_named() -> None:
    gateway = GatewayStub(status=403, body={"error": {"code": "policy_denied"}})
    reader = reader_for(gateway)

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway refused: policy_denied."
    )


async def test_falls_back_to_the_status_when_the_refusal_carries_no_code() -> None:
    gateway = GatewayStub(status=502, body={})
    reader = reader_for(gateway)

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway refused: HTTP 502."
    )


async def test_reports_an_empty_release_rather_than_pretending_it_succeeded() -> None:
    gateway = GatewayStub(body={"credentials": []})
    reader = reader_for(gateway)

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway released nothing."
    )


async def test_reports_an_unreachable_gateway_instead_of_raising() -> None:
    gateway = GatewayStub(throws=True)
    reader = reader_for(gateway)

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway could not be reached."
    )


async def test_survives_a_gateway_that_answers_with_something_other_than_json() -> None:
    class NotJson:
        async def __call__(
            self, url: str, *, headers: Mapping[str, str], body: bytes
        ) -> GatewayReply:
            return GatewayReply(500, b"<html>bad gateway</html>")

    reader = KitReader(gateway_url=GATEWAY, transport=NotJson())

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway refused: HTTP 500."
    )


def test_a_released_credential_does_not_print() -> None:
    released = Released(credentials=tuple(RELEASED))

    assert "ghp_x" not in repr(released)
    assert repr(released) == "Released(credentials=<1 redacted>)"


def test_refuses_a_gateway_url_that_could_not_receive_a_token() -> None:
    with pytest.raises(ValueError, match="http"):
        KitReader(gateway_url="file:///etc/passwd")
