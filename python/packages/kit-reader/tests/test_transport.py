"""The default transport, which has no Node counterpart: `fetch` is a global
there, and stdlib `urllib` needs a thread and treats a refusal as an exception.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import ClassVar

import pytest

from keydris_kit_reader import KitReader, Refused, Released, urllib_transport

RELEASED = [{"type": "header", "name": "Authorization", "prefix": "", "value": "Bearer ghp_x"}]


class Gateway(BaseHTTPRequestHandler):
    """Answers `/release` with credentials and `/refuse` with a policy denial."""

    protocol_version = "HTTP/1.1"
    received: ClassVar[list[object]] = []

    # do_POST, log_message: the names BaseHTTPRequestHandler dispatches on.
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        Gateway.received.append(json.loads(self.rfile.read(length)))

        status: int
        document: dict[str, object]
        if self.path == "/refuse":
            status, document = 403, {"error": {"code": "policy_denied"}}
        else:
            status, document = 200, {"credentials": RELEASED}

        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Quiet: the test's output is the assertions."""


@pytest.fixture
def gateway() -> Iterator[str]:
    Gateway.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def tool_call(token: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "github_whoami",
            "arguments": {},
            "_meta": {"keydris/kit_action_token": token},
        },
    }


async def test_redeems_over_a_real_socket(gateway: str) -> None:
    reader = KitReader(gateway_url=f"{gateway}/release")

    redemption = await reader.redeem(tool_call("action-token"))

    assert isinstance(redemption, Released)
    assert redemption.credentials[0]["value"] == "Bearer ghp_x"
    assert Gateway.received == [
        {
            "token": "action-token",
            "mcp": {
                "method": "tools/call",
                "action_name": "github_whoami",
                "parameters": {},
            },
        }
    ]


async def test_a_refusal_is_an_answer_not_an_exception(gateway: str) -> None:
    reader = KitReader(gateway_url=f"{gateway}/refuse")

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway refused: policy_denied."
    )


async def test_a_refusal_arrives_with_its_status_and_body(gateway: str) -> None:
    reply = await urllib_transport(5.0)(
        f"{gateway}/refuse", headers={"content-type": "application/json"}, body=b"{}"
    )

    assert reply.status == 403
    assert json.loads(reply.body) == {"error": {"code": "policy_denied"}}


async def test_an_unreachable_gateway_is_reported_not_raised() -> None:
    # Port 1 on the loopback: nothing listens, and nothing can be started there.
    reader = KitReader(gateway_url="http://127.0.0.1:1/gateway/credentials", timeout=2.0)

    assert await reader.redeem(tool_call("action-token")) == Refused(
        problem="The Keydris gateway could not be reached."
    )
