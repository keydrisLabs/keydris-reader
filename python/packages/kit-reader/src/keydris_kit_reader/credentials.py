"""Spending a released credential on the outbound request."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from keydris_kit_reader.types import CredentialEnvelope

__all__ = ["apply_credentials"]


def apply_credentials(
    credentials: Sequence[CredentialEnvelope],
    url: str,
    headers: MutableMapping[str, str],
) -> str:
    """Applies released credentials to an outbound request.

    `headers` is updated in place. The URL is returned rather than mutated,
    because a Python string cannot be: a query credential yields a new URL,
    replacing any existing parameter of the same name.
    """
    query: list[tuple[str, str]] = []

    for credential in credentials:
        value = f"{credential['prefix']}{credential['value']}"
        if credential["type"] == "query":
            query.append((credential["name"], value))
        else:
            headers[credential["name"]] = value

    if not query:
        return url

    replaced = {name for name, _ in query}
    parts = urlsplit(url)
    kept = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if name not in replaced
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept + query), parts.fragment)
    )
