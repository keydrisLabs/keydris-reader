"""Ports `node/packages/kit-reader/src/token.test.ts`."""

from __future__ import annotations

from typing import Any

from keydris_kit_reader import calls_a_tool, kit_action_token_from
from keydris_kit_reader.types import TokenLookup


def tool_call(token: str | None = None, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"name": "github_whoami", "arguments": arguments or {}}
    if token:
        params["_meta"] = {"keydris/kit_action_token": token}
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


def test_binds_redemption_to_the_actual_tool_call() -> None:
    result = kit_action_token_from(tool_call("action-token", {"verbose": True}))

    assert result.token == "action-token"
    assert result.context == {
        "mcp": {
            "method": "tools/call",
            "action_name": "github_whoami",
            "parameters": {"verbose": True},
        }
    }


def test_rejects_a_batch_that_tries_to_reuse_one_action_token() -> None:
    result = kit_action_token_from([tool_call("action-token"), tool_call("action-token")])

    assert result.problem == "A KIT action token can authorize only one MCP action per request."


def test_strips_a_bearer_scheme_from_the_injected_token() -> None:
    assert kit_action_token_from(tool_call("Bearer action-token")).token == "action-token"


def test_finds_nothing_in_a_body_that_carries_no_token() -> None:
    assert kit_action_token_from(tool_call()) == TokenLookup()
    assert (
        kit_action_token_from({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) == TokenLookup()
    )


def test_reports_a_malformed_token_rather_than_ignoring_it() -> None:
    call = tool_call()
    call["params"]["_meta"] = {"keydris/kit_action_token": 42}

    assert kit_action_token_from(call).problem == "The Keydris KIT action token is malformed."


def test_reports_a_tokenized_call_whose_name_or_arguments_are_malformed() -> None:
    named = tool_call("action-token")
    named["params"]["name"] = ""
    assert kit_action_token_from(named).problem == "The tokenized MCP tool call is malformed."

    argued = tool_call("action-token")
    argued["params"]["arguments"] = []
    assert kit_action_token_from(argued).problem == "The tokenized MCP tool call is malformed."


def test_recognizes_which_bodies_cost_a_secret() -> None:
    assert calls_a_tool(tool_call("action-token")) is True
    assert calls_a_tool([{"method": "tools/list"}, tool_call()]) is True
    assert calls_a_tool({"method": "initialize"}) is False
    assert calls_a_tool(None) is False
