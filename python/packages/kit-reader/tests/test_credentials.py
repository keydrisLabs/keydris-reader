"""Ports `node/packages/kit-reader/src/credentials.test.ts`."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from keydris_kit_reader import apply_credentials


def test_puts_a_header_credential_on_the_outbound_headers_prefix_included() -> None:
    headers: dict[str, str] = {}

    url = apply_credentials(
        [{"type": "header", "name": "Authorization", "prefix": "Bearer ", "value": "ghp_secret"}],
        "https://api.github.com/user",
        headers,
    )

    assert headers == {"Authorization": "Bearer ghp_secret"}
    assert url == "https://api.github.com/user"


def test_puts_a_query_credential_on_the_outbound_url() -> None:
    headers: dict[str, str] = {}

    url = apply_credentials(
        [{"type": "query", "name": "api_key", "prefix": "", "value": "k_secret"}],
        "https://example.test/v1/thing?page=2",
        headers,
    )

    query = parse_qs(urlsplit(url).query)
    assert query["api_key"] == ["k_secret"]
    assert query["page"] == ["2"]
    assert headers == {}


def test_applies_every_released_credential() -> None:
    headers: dict[str, str] = {}

    url = apply_credentials(
        [
            {"type": "header", "name": "Authorization", "prefix": "Bearer ", "value": "a"},
            {"type": "header", "name": "X-Tenant", "prefix": "", "value": "b"},
            {"type": "query", "name": "key", "prefix": "v1_", "value": "c"},
        ],
        "https://example.test/",
        headers,
    )

    assert headers == {"Authorization": "Bearer a", "X-Tenant": "b"}
    assert parse_qs(urlsplit(url).query)["key"] == ["v1_c"]


def test_replaces_an_existing_parameter_of_the_same_name() -> None:
    url = apply_credentials(
        [{"type": "query", "name": "api_key", "prefix": "", "value": "fresh"}],
        "https://example.test/v1?api_key=stale&page=2",
        {},
    )

    query = parse_qs(urlsplit(url).query)
    assert query["api_key"] == ["fresh"]
    assert query["page"] == ["2"]
