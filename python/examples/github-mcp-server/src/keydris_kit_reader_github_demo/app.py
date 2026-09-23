"""Wiring: one reader for the process, a stateless MCP endpoint on `/mcp`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from keydris_kit_reader import KitReader, ReaderTelemetry, reader_api_url
from keydris_kit_reader_github_demo.config import config
from keydris_kit_reader_github_demo.server import build_server


def build_app() -> Starlette:
    # One reader for the process: it holds no per-request state, only where to
    # redeem and which legacy header to fall back to.
    if bool(config.api_url) != bool(config.installation_key):
        raise ValueError("Set both KEYDRIS_API_URL and KEYDRIS_MCP_KEY")
    telemetry = (
        ReaderTelemetry(
            api_url=config.api_url,
            api_key=config.installation_key,
            on_dropped=lambda: print("Keydris telemetry delivery dropped"),
        )
        if config.api_url and config.installation_key
        else None
    )
    reader = KitReader(
        gateway_url=urljoin(reader_api_url(config.api_url), "gateway/credentials")
        if config.api_url
        else config.gateway_url,
        token_header=config.token_header,
        installation_key=config.installation_key,
        telemetry=telemetry,
    )
    mcp = build_server(reader)

    # `custom_route` carries no return annotation in the SDK, so strict mypy reads
    # it as untyped; the handler below is annotated.
    @mcp.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    async def healthz(_request: Request) -> Response:
        return JSONResponse({"ok": True})

    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        # Stateless: a fresh transport per request and no session id. An MCP
        # session would otherwise outlive the short-lived token that authorized
        # it, and the released credential would have to live somewhere between
        # requests.
        stateless_http=True,
        # One JSON body per POST instead of an SSE stream, so a curl of the demo
        # is readable.
        json_response=True,
        # The SDK answers 421 to any Host it was not told to expect. Localhost
        # needs no allowlist; anything else does.
        transport_security=(
            TransportSecuritySettings(allowed_hosts=list(config.allowed_hosts))
            if config.allowed_hosts
            else None
        ),
    )
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[Any]:
        if telemetry:
            telemetry.start()
        try:
            async with original_lifespan(application) as state:
                yield state
        finally:
            if telemetry:
                await telemetry.close()

    app.router.lifespan_context = lifespan
    return app


app = build_app()
