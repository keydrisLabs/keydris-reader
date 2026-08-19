"""Env is read here and nowhere else — the library never touches os.environ."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Config:
    host: str
    """Loopback by default: the demo is reachable from the proxy on the same
    machine without being reachable from the network."""

    port: int
    """Whatever the proxy dials must match, because the proxy's `dst_addr`
    becomes the token's `dst`, and the gateway looks up the credential by that
    host."""

    gateway_url: str
    """Where this server redeems the token it was handed."""

    token_header: str
    """Legacy `/agent/authorize` header accepted as a fallback. `mcp_kit_reader`
    requests carry their action-scoped token in MCP params._meta instead."""

    github_api_base: str

    allowed_hosts: tuple[str, ...]
    """The SDK answers 421 to any Host it was not told to expect, so anything
    other than localhost has to be named."""


def load() -> Config:
    hosts = os.environ.get("KEYDRIS_ALLOWED_HOSTS", "").strip()
    return Config(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8788")),
        gateway_url=os.environ.get(
            "KEYDRIS_GATEWAY_URL", "http://localhost:8080/gateway/credentials"
        ),
        token_header=os.environ.get("KEYDRIS_TOKEN_HEADER", "authorization").strip().lower(),
        github_api_base=os.environ.get("GITHUB_API_BASE", "https://api.github.com"),
        allowed_hosts=tuple(host.strip() for host in hosts.split(",") if host.strip()),
    )


config = load()
