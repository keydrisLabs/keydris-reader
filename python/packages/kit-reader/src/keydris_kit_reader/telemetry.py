"""Bounded, best-effort reader reports. Tool execution is never retried here."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from keydris_kit_reader.transport import Transport, urllib_transport

Outcome = Literal["SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"]


def reader_api_url(raw: str) -> str:
    parts = urlsplit(raw)
    loopback = parts.hostname in ("localhost", "::1") or bool(
        re.fullmatch(r"127(?:\.\d{1,3}){3}", parts.hostname or "")
    )
    if (
        not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or (parts.scheme != "https" and not (parts.scheme == "http" and loopback))
    ):
        raise ValueError("API URL must use HTTPS (except loopback) without credentials or query")
    return raw.rstrip("/") + "/"


class ReaderTelemetry:
    """Asyncio reporter; start and close inside the application's async lifespan.

    A custom transport must not follow redirects. Reports contain no tool arguments,
    results, provider bodies, or exception messages. Queue overflow calls on_dropped.
    """

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        transport: Transport | None = None,
        on_dropped: Callable[[], None] | None = None,
        retry_delay: float = 0.15,
    ) -> None:
        self._base = reader_api_url(api_url)
        self._key = api_key
        self._transport = transport or urllib_transport(3.0)
        self._on_dropped = on_dropped
        self._retry_delay = retry_delay
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=200)
        self._worker: asyncio.Task[None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._closed = False

    def _drop(self) -> None:
        try:
            if self._on_dropped:
                self._on_dropped()
        except Exception:
            pass

    def _enqueue(self, path: str, body: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait((path, body))
        except asyncio.QueueFull:
            self._drop()
            return
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        while not self._queue.empty():
            path, body = self._queue.get_nowait()
            try:
                for attempt in range(3):
                    try:
                        reply = await asyncio.wait_for(
                            self._transport(
                                urljoin(self._base, path),
                                headers={
                                    "content-type": "application/json",
                                    "authorization": f"Bearer {self._key}",
                                },
                                body=json.dumps(body).encode(),
                            ),
                            timeout=3.0,
                        )
                        if 200 <= reply.status < 300:
                            break
                        if reply.status < 500 and reply.status != 429:
                            self._drop()
                            break
                    except Exception:
                        pass
                    if attempt == 2:
                        self._drop()
                    else:
                        await asyncio.sleep(self._retry_delay * 2**attempt)
            finally:
                self._queue.task_done()

    def start(self) -> None:
        if self._heartbeat is not None or self._closed:
            return
        self._register()
        self._heartbeat = asyncio.create_task(self._heartbeats())

    def _register(self) -> None:
        self._enqueue(
            "gateway/reader/register",
            {
                "schema_version": 1,
                "reader_version": "0.3.0",
                "capabilities": ["tool_lifecycle", "provider_outcomes"],
            },
        )

    async def _heartbeats(self) -> None:
        while True:
            await asyncio.sleep(60)
            self._register()

    def event(self, event: dict[str, Any]) -> None:
        self._enqueue("gateway/reader/events", event)

    def outcome(
        self,
        receipt: str,
        outcome: Outcome,
        *,
        provider_status: int | None = None,
        error_code: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"receipt": receipt, "outcome": outcome}
        if provider_status is not None:
            body["provider_status"] = provider_status
        if error_code is not None:
            body["error_code"] = error_code
        self._enqueue("gateway/outcomes", body)

    async def flush(self, timeout: float = 5.0) -> None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout)

    async def close(self) -> None:
        self._closed = True
        if self._heartbeat:
            self._heartbeat.cancel()
            await asyncio.gather(self._heartbeat, return_exceptions=True)
        await self.flush()
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
            self._drop()


def start_observation(
    telemetry: ReaderTelemetry | None, action_name: str, token: str | None = None
) -> Callable[[Outcome, str | None], None]:
    started = time.monotonic()
    finished = False
    common: dict[str, Any] = {
        "schema_version": 1,
        "invocation_id": str(uuid4()),
        "method": "tools/call",
        "action_name": action_name,
    }
    if token:
        common["action_token"] = token

    def send(phase: str, **fields: Any) -> None:
        if telemetry:
            telemetry.event(
                {
                    **common,
                    "event_id": str(uuid4()),
                    "phase": phase,
                    "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    **fields,
                }
            )

    send("started")

    def finish(outcome: Outcome, error_code: str | None = None) -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        send(
            "completed",
            outcome=outcome,
            duration_ms=min(86_400_000, max(0, round((time.monotonic() - started) * 1000))),
            **({"error_code": error_code} if error_code else {}),
        )

    return finish
