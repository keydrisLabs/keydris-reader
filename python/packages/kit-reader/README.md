# keydris-kit-reader

Redeem a single-use Keydris **KIT action token** for the credential your MCP server needs upstream.

Drop this into any MCP server and it stops holding secrets. Nothing is configured on the server,
baked into its image, or held between requests: for each `tools/call`, the library exchanges the
action-scoped token the Keydris proxy injected for the credential that call needs, and hands it back
for the one outbound request it authorizes.

```
proxy ──► POST /mcp
          params._meta["keydris/kit_action_token"] = token
                                                  ──► your server
          your server ──► POST {gateway_url}  {token, mcp:{action_name, parameters},
                                               target:{host, path, method}}
                       ◄── {credentials:[{type,name,prefix,value}]}
          your server ──► the upstream API, credential applied
```

Zero runtime dependencies. `mcp` is needed only for the `keydris_kit_reader.mcp` adapter.

## Install

```bash
pip install keydris-kit-reader          # or: uv add keydris-kit-reader
pip install 'keydris-kit-reader[mcp]'   # if you serve with the MCP Python SDK
```

Python >= 3.10. `redeem` is async.

## Use it

Create one reader at startup — it holds no per-request state, only where to redeem.

```python
from keydris_kit_reader import KitReader

reader = KitReader(gateway_url="https://api.keydris.com/gateway/credentials")
```

### With the MCP Python SDK

`keydris_kit_reader.mcp` is a middleware factory. The gateway redeems a KIT action token only
together with the downstream `target` (host, path, method) of the request it authorizes — which is
known inside the tool at request time, not when the MCP request arrives. So the middleware does not
redeem: it arms a one-shot spend, reachable via `current_spend()` for the duration of the call.

```python
from mcp.server import MCPServer
from keydris_kit_reader.mcp import current_spend, keydris_credentials

mcp = MCPServer("your-server", middleware=[keydris_credentials(reader)])
```

### With anything else

The middleware is a small convenience over one call. A raw Starlette route, FastAPI, a Lambda
handler, or an stdio loop all use the reader directly, on the JSON-RPC body — at the moment the
outbound request is known:

```python
redemption = await reader.redeem(
    body,
    header=request.headers.get(reader.token_header),
    target={"host": "api.github.com", "path": "/user", "method": "GET"},
)
```

### Then spend it

Inside the tool handler, call the spend with the target of the one outbound request — hostname
without port, path without query — then `apply_credentials` puts the released envelope onto it, as
a header or a query parameter, whichever the vault entry specified.

```python
from keydris_kit_reader import apply_credentials
from keydris_kit_reader.mcp import current_spend
from mcp.server.mcpserver.exceptions import ToolError

redemption = await current_spend()({"host": "api.github.com", "path": "/user", "method": "GET"})
if not redemption.ok:
    raise ToolError(redemption.problem)

headers = {"accept": "application/json"}
url = apply_credentials(redemption.credentials, "https://api.github.com/user", headers)

response = await client.get(url, headers=headers)
```

`headers` is updated in place; the URL is returned, because a Python string cannot be mutated the way
Node's `URL` can. A `ToolError` — or any exception — reaches the agent as an `isError` result whose
text is the message, which is what makes a refusal readable rather than a crash.

## What it guarantees

- **Only `tools/call` costs a secret.** `redeem()` returns `None` for `initialize`, `tools/list`, and
  anything else that invokes no tool — the gateway is never called. A client with no token can still
  connect and see what is on offer; it discovers it needs one only when it asks for something that
  reveals a credential.
- **One token authorizes one action.** Redemption sends the tool name, the exact arguments, and
  the downstream target alongside the token, so the gateway evaluates policy against the call that
  is really about to happen. A batch that reuses a token is refused before the gateway is touched,
  and so is a second spend of an already-spent request.
- **Failures are answers, not crashes.** `redeem()` never raises. A missing token, a malformed one, a
  gateway refusal naming its code, an unreachable gateway — each comes back as
  `Refused(problem=...)` for you to return as a tool error the agent can read.
- **A released secret does not print.** `Released.__repr__` is redacted, so an envelope that reaches
  a traceback or a log line does not take the credential with it.

Two things are yours to get right, because the library cannot enforce them:

- **Serve stateless.** A long-lived session outlives the short-lived token that authorized it. The
  middleware scopes each spend to the call it was armed for and drops it on the way out;
  don't lift one out of that scope, and never cache a `Redemption`.
- **Never log `credentials`.** Log the `problem` side freely; it carries no secret.

## API

```python
KitReader(*, gateway_url, token_header="authorization", transport=None, timeout=10.0)
```

| Option         | Default          | Meaning                                                              |
| -------------- | ---------------- | -------------------------------------------------------------------- |
| `gateway_url`  | _(required)_     | The control plane's redemption endpoint. Must be `http(s)`.          |
| `token_header` | `authorization`  | Legacy `/agent/authorize` header accepted as a fallback, lowercased. |
| `transport`    | stdlib `urllib`  | Injectable, for tests or an instrumented client.                     |
| `timeout`      | `10.0`           | Seconds the default transport waits on the gateway.                  |

```python
reader.token_header -> str                      # lowercased
reader.calls_a_tool(body) -> bool
await reader.redeem(body, *, header=None, target=None) -> Redemption | None

Redemption = Released | Refused
Released(credentials: tuple[CredentialEnvelope, ...], ok: Literal[True])
Refused(problem: str, ok: Literal[False])
CredentialEnvelope = TypedDict('type': 'header' | 'query', 'name', 'prefix', 'value')
```

Both arms carry a literal `ok`, so a type checker narrows the union on it the way TypeScript narrows
a discriminated union.

Also exported: `apply_credentials`, `calls_a_tool`, `kit_action_token_from` and `token_from` (the raw
parsers, if you want the token and its context without redeeming), `KIT_ACTION_TOKEN_META_KEY`, and
`GatewayReply` / `Transport` / `urllib_transport` for the transport seam.

Both token transports are accepted with or without a `Bearer ` scheme. If a request carries both a
KIT action token and a header token and they disagree, redemption refuses rather than picking one.

### Bringing your own client

The default transport is stdlib `urllib` run off the event loop, which is what keeps this package
dependency-free. If your server already has an HTTP client — and it does, if you serve with `mcp` —
hand the reader that one instead:

```python
from keydris_kit_reader import GatewayReply, KitReader


async def transport(url, *, headers, body):
    response = await client.post(url, headers=headers, content=body)
    return GatewayReply(response.status_code, response.content)


reader = KitReader(gateway_url=..., transport=transport)
```

Raising from a transport is how it says the gateway could not be reached; a refusal is a
`GatewayReply` carrying the refusing status, not an exception.

## A worked example

[`examples/github-mcp-server`](https://github.com/keydrisLabs/keydris-reader/tree/main/python/examples/github-mcp-server)
is a complete MCP server built on this library — one `github_whoami` tool, no credential of its
own — with instructions for running it against a stub gateway and wiring policy to gate both the
action and the credential release.

The same library exists for Node as
[`@keydris/kit-reader`](https://www.npmjs.com/package/@keydris/kit-reader); the `_meta` key, the
redemption body, and the `problem` strings are identical across both.

## Development

```bash
uv sync --all-packages
uv run pytest
uv run mypy
uv run ruff check .
uv build --package keydris-kit-reader
```

Releases are cut by pushing a `kit-reader-py-v*` tag; see
[the workspace README](https://github.com/keydrisLabs/keydris-reader/tree/main/python#releasing-the-library).

## Compatibility

`keydris_kit_reader.mcp` targets the MCP Python SDK's server middleware, which the SDK documents as
provisional within 2.x. The rest of the library depends on nothing but the standard library and is
unaffected.

## License

[Apache License 2.0](https://github.com/keydrisLabs/keydris-reader/blob/main/LICENSE).

## Kit Reader enrollment and activity logs

1. Start the MCP so `initialize` and `tools/list` are reachable.
2. In Keydris MCP servers, select **Kit Reader**, test the connection, and connect it.
3. Create an installation key for that connection. Only an integration manager in the owning organization can issue it.
4. Set `KEYDRIS_API_URL` and `KEYDRIS_MCP_KEY` in the deployment's secret settings and restart.
5. Refresh enrollment status, then open the MCP's **Sessions** or **Logs** view.

The key identifies one installation of one MCP in one organization. It is separate from upstream authentication headers and ordinary user API keys. Registration and heartbeat are outbound requests; the discovery test does not require the key. Rotation immediately replaces the old key; revoked or expired keys stop reporting and credential redemption.

Reports distinguish tool completion from provider execution. A tool returning `isError` is a failure even when the MCP transport returned HTTP 200. A provider network failure is UNKNOWN and never triggers another provider request. Arguments, tool results, credentials, response bodies and exception messages are excluded. Calls without a verified action token remain unattributed to a session. Runtime client IP and the MCP peer IP are separate observations.

Delivery is best effort: a 200-item memory queue, three delivery attempts, fixed configured destination, no redirects, 60-second registration heartbeat, and a bounded five-second flush on `close()`. Abrupt process termination can lose queued reports; authorization and credential-release evidence remains in Keydris. Call `close()` from the application's shutdown lifecycle. Gateway-managed MCPs do not enroll or use this key.

### Python setup

```python
from urllib.parse import urljoin
from keydris_kit_reader import KitReader, ReaderTelemetry, reader_api_url

telemetry = ReaderTelemetry(api_url=api_url, api_key=installation_key)
reader = KitReader(
    gateway_url=urljoin(reader_api_url(api_url), "gateway/credentials"),
    installation_key=installation_key,
    telemetry=telemetry,
)
# Inside your asyncio application lifespan:
telemetry.start()
# Register keydris_credentials(reader) as usual; it observes actual tool results.
# On shutdown:
await telemetry.close()
```

The reporter uses asyncio and a bounded background queue. Call `Released.report_outcome("SUCCEEDED", provider_status=200)` after a provider response, or UNKNOWN on uncertain dispatch. The GitHub example demonstrates this and closes reporting in the application lifespan. Custom injected transports must enforce HTTPS and refuse redirects.
