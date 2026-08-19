# @keydris/kit-reader

Redeem a single-use Keydris **KIT action token** for the credential your MCP server needs upstream.

Drop this into any MCP server and it stops holding secrets. Nothing is configured on the server,
baked into its image, or held between requests: for each `tools/call`, the library exchanges the
action-scoped token the Keydris proxy injected for the credential that call needs, and hands it back
for the one outbound request it authorizes.

```
proxy ──► POST /mcp
          params._meta["keydris/kit_action_token"] = token
                                                  ──► your server
          your server ──► POST {gatewayUrl}  {token, mcp:{action_name, parameters}}
                       ◄── {credentials:[{type,name,prefix,value}]}
          your server ──► the upstream API, credential applied
```

Zero runtime dependencies. `express` is an optional peer, needed only for the `/express` subpath.

## Install

```bash
npm install @keydris/kit-reader
```

Node >= 20 (the library uses the global `fetch`, `URL`, and `Headers`). ESM only.

## Use it

Create one reader at startup — it holds no per-request state, only where to redeem.

```ts
import { createKitReader } from '@keydris/kit-reader';

const reader = createKitReader({
  gatewayUrl: 'https://api.keydris.com/gateway/credentials',
});
```

### With Express

The `/express` subpath is a middleware factory. It leaves the result on `req.redemption`, and
importing it is what adds that property to the `Request` type.

```ts
import { keydrisCredentials } from '@keydris/kit-reader/express';

app.post('/mcp', express.json(), keydrisCredentials(reader), async (req, res) => {
  const server = createYourMcpServer(req.redemption); // build per request
  // …connect a transport and handle the request
});
```

### With anything else

The middleware is a nine-line convenience over one call. Fastify, Hono, a Lambda handler, or a raw
`node:http` server all use the reader directly:

```ts
const redemption = await reader.redeem(jsonRpcBody, {
  header: request.headers[reader.tokenHeader], // optional legacy fallback
});
```

### Then spend it

Inside the tool handler, `applyCredentials` puts the released envelope onto the outbound request —
as a header or a query parameter, whichever the vault entry specified.

```ts
import { applyCredentials } from '@keydris/kit-reader';

if (!redemption?.ok) {
  return { content: [{ type: 'text', text: redemption?.problem ?? 'No credential was released.' }], isError: true };
}

const url = new URL('/user', 'https://api.github.com');
const headers = new Headers({ accept: 'application/json' });
applyCredentials(redemption.credentials, url, headers);

const response = await fetch(url, { headers });
```

## What it guarantees

- **Only `tools/call` costs a secret.** `redeem()` resolves to `undefined` for `initialize`,
  `tools/list`, and anything else that invokes no tool — the gateway is never called. A client with
  no token can still connect and see what is on offer; it discovers it needs one only when it asks
  for something that reveals a credential.
- **One token authorizes one action.** Redemption sends the tool name and the exact arguments
  alongside the token, so the gateway evaluates policy against the call that is really about to
  happen. A batch that reuses a token is refused before the gateway is touched.
- **Failures are answers, not crashes.** `redeem()` never rejects. A missing token, a malformed one,
  a gateway refusal naming its code, an unreachable gateway — each comes back as
  `{ ok: false, problem }` for you to return as a tool error the agent can read.

Two things are yours to get right, because the library cannot enforce them:

- **Build your MCP server per request, stateless.** A long-lived session outlives the short-lived
  token that authorized it. Keep the released credential on the stack of the call it was released
  for; never cache a `Redemption`.
- **Never log `credentials`.** Log the `problem` side freely; it carries no secret.

## API

```ts
createKitReader(options: KitReaderOptions): KitReader
```

| Option        | Default         | Meaning                                                             |
| ------------- | --------------- | ------------------------------------------------------------------- |
| `gatewayUrl`  | _(required)_    | The control plane's redemption endpoint.                              |
| `tokenHeader` | `authorization` | Legacy `/agent/authorize` header accepted as a fallback, lowercased. |
| `fetch`       | global `fetch`  | Injectable, for tests or an instrumented client.                    |

```ts
type KitReader = {
  readonly tokenHeader: string;
  callsATool(body: unknown): boolean;
  redeem(body: unknown, source?: { header?: string }): Promise<Redemption | undefined>;
};

type Redemption =
  | { ok: true; credentials: CredentialEnvelope[] }
  | { ok: false; problem: string };

type CredentialEnvelope = { type: 'header' | 'query'; name: string; prefix: string; value: string };
```

Also exported: `applyCredentials`, `callsATool`, `kitActionTokenFrom` (the raw parser, if you need
the token and its context without redeeming), and `KIT_ACTION_TOKEN_META_KEY`.

Both token transports are accepted with or without a `Bearer ` scheme. If a request carries both a
KIT action token and a header token and they disagree, redemption refuses rather than picking one.

## A worked example

[`examples/github-mcp-server`](../../examples/github-mcp-server) is a complete MCP server built on
this library — one `github_whoami` tool, no credential of its own — with instructions for running it
against a stub gateway, deploying it, and wiring policy to gate both the action and the credential
release.

## Development

```bash
npm run typecheck
npm test          # node:test over src/*.test.ts
npm run build     # emit dist/ (tests excluded)
```
