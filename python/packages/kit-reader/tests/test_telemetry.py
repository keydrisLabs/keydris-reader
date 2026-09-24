"""Enrollment telemetry and actual MCP handler outcomes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

import pytest
from mcp.server.context import HandlerResult, ServerRequestContext
from mcp_types import CallToolResult

from keydris_kit_reader import GatewayReply, KitReader, ReaderTelemetry, reader_api_url
from keydris_kit_reader.mcp import keydris_credentials


async def test_retries_same_event_without_tool_arguments_or_results() -> None:
    reports: list[dict[str, Any]] = []

    async def transport(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        assert headers["authorization"] == "Bearer machine-key"
        reports.append(json.loads(body))
        return GatewayReply(503 if len(reports) == 1 else 200, b"{}")

    telemetry = ReaderTelemetry(
        api_url="https://keydris.test", api_key="machine-key", transport=transport, retry_delay=0
    )
    reader = KitReader(
        gateway_url="https://keydris.test/gateway/credentials",
        installation_key="machine-key",
        telemetry=telemetry,
    )
    ctx: ServerRequestContext[Any, Any] = ServerRequestContext(
        session=cast(Any, None),
        lifespan_context={},
        protocol_version="2025-11-25",
        method="tools/call",
        params={"name": "weather", "arguments": {"private": "argument"}},
    )

    async def handler(context: ServerRequestContext[Any, Any]) -> HandlerResult:
        return CallToolResult(content=[], is_error=True)

    result = await keydris_credentials(reader)(ctx, handler)
    assert isinstance(result, CallToolResult)
    await telemetry.flush()
    assert len(reports) == 3
    assert reports[0] == reports[1]
    assert reports[2]["outcome"] == "FAILED"
    assert "private" not in json.dumps(reports)
    assert "session_id" not in reports[0]
    await telemetry.close()


async def test_registration_is_idempotent_and_permanent_refusals_do_not_retry() -> None:
    reports: list[str] = []
    drops: list[bool] = []

    async def transport(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        reports.append(url)
        return GatewayReply(401, b"{}")

    telemetry = ReaderTelemetry(
        api_url="https://keydris.test",
        api_key="key",
        transport=transport,
        on_dropped=lambda: drops.append(True),
    )
    telemetry.start()
    telemetry.start()
    await telemetry.flush()
    await telemetry.close()
    assert reports == ["https://keydris.test/gateway/reader/register"]
    assert drops == [True]


async def test_redemption_carries_installation_key_and_preserves_receipt() -> None:
    receipt = "kor_" + "a" * 43
    reports: list[dict[str, Any]] = []

    async def transport(url: str, *, headers: Mapping[str, str], body: bytes) -> GatewayReply:
        assert headers["authorization"] == "Bearer key"
        reports.append(json.loads(body))
        return GatewayReply(
            200,
            json.dumps(
                {
                    "credentials": [
                        {"type": "header", "name": "authorization", "prefix": "", "value": "secret"}
                    ],
                    "decision_id": "decision",
                    "outcome_receipt": receipt,
                }
            ).encode(),
        )

    telemetry = ReaderTelemetry(api_url="https://keydris.test", api_key="key", transport=transport)
    reader = KitReader(
        gateway_url="https://keydris.test/gateway/credentials",
        installation_key="key",
        telemetry=telemetry,
        transport=transport,
    )
    result = await reader.redeem(
        {"method": "tools/call", "params": {"name": "weather"}}, header="legacy-token"
    )
    assert result is not None and result.ok
    assert result.outcome_receipt == receipt
    result.report_outcome("UNKNOWN", error_code="provider_transport_unknown")
    await telemetry.flush()
    assert reports[-1] == {
        "receipt": receipt,
        "outcome": "UNKNOWN",
        "error_code": "provider_transport_unknown",
    }
    assert receipt not in repr(result)
    await telemetry.close()


@pytest.mark.parametrize("url", ["http://external.test", "https://name:secret@keydris.test"])
def test_refuses_unsafe_telemetry_url(url: str) -> None:
    with pytest.raises(ValueError):
        reader_api_url(url)
