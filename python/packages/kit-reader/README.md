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
          your server ──► POST {gateway_url}  {token, mcp:{action_name, parameters}}
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

`keydris_kit_reader.mcp` is a middleware factory. Register it on the server once; it leaves the
result on `current_redemption()` for the duration of the call.

```python
from mcp.server import MCPServer
from keydris_kit_reader.mcp import current_redemption, keydris_credentials

mcp = MCPServer("your-server", middleware=[keydris_credentials(reader)])
```

### With anything else

The middleware is a small convenience over one call. A raw Starlette route, FastAPI, a Lambda
handler, or an stdio loop all use the reader directly, on the JSON-RPC body:

```python
redemption = await reader.redeem(body, header=request.headers.get(reader.token_header))
```

### Then spend it

Inside the tool handler, `apply_credentials` puts the released envelope onto the outbound request —
as a header or a query parameter, whichever the vault entry specified.

```python
from keydris_kit_reader import apply_credentials
from keydris_kit_reader.mcp import current_redemption
from mcp.server.mcpserver.exceptions import ToolError

redemption = current_redemption()
if redemption is None or not redemption.ok:
    raise ToolError(redemption.problem if redemption else "No credential was released.")

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
- **One token authorizes one action.** Redemption sends the tool name and the exact arguments
  alongside the token, so the gateway evaluates policy against the call that is really about to
  happen. A batch that reuses a token is refused before the gateway is touched.
- **Failures are answers, not crashes.** `redeem()` never raises. A missing token, a malformed one, a
  gateway refusal naming its code, an unreachable gateway — each comes back as
  `Refused(problem=...)` for you to return as a tool error the agent can read.
- **A released secret does not print.** `Released.__repr__` is redacted, so an envelope that reaches
  a traceback or a log line does not take the credential with it.

Two things are yours to get right, because the library cannot enforce them:

- **Serve stateless.** A long-lived session outlives the short-lived token that authorized it. The
  middleware scopes each redemption to the call it was released for and drops it on the way out;
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
await reader.redeem(body, *, header=None) -> Redemption | None

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
