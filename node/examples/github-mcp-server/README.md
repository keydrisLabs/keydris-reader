# github-mcp-server — a sample @keydris/kit-reader implementation

A demo MCP server that holds no credential of its own. It exposes one tool, `github_whoami`, and
gets the GitHub PAT it needs at call time by redeeming the action-scoped token the proxy injected
into the MCP request.

All of the token handling lives in [`@keydris/kit-reader`](../../packages/kit-reader). What is left
here is what any MCP server has to write for itself: the tool, the upstream API client, and the
HTTP wiring.

```
agent ──► proxy ──► POST /v1/runtime/mcp/kit-action-tokens ──► KIT action token
          proxy ──► POST /mcp
                    params._meta["keydris/kit_action_token"] = token
                                                            ──► this server
                    this server ──► POST /gateway/credentials
                                   {token, mcp}
                                ◄── {credentials:[{type,name,prefix,value}]}
                    this server ──► GET api.github.com/user  (credential applied)
```

For compatibility with the legacy `/agent/authorize` flow, the server also accepts the token from
the configured HTTP header. If both transports are present, they must contain the same token.

## What this example is made of

| File                              | What it shows                                                     |
| --------------------------------- | ----------------------------------------------------------------- |
| [`src/index.ts`](src/index.ts)     | Wiring: one `createKitReader`, the Express middleware, stateless per-request MCP transport. |
| [`src/server.ts`](src/server.ts)   | The tool, built per request against that request's `Redemption`.   |
| [`src/github.ts`](src/github.ts)   | Spending the released credential with `applyCredentials`.          |
| [`src/config.ts`](src/config.ts)   | Env, read here only — the library never touches `process.env`.     |

## The one thing to get right: credential release scope

For the KIT flow, the gateway derives the release scope from the registered MCP connection URL. For
the hosted demo that is `POST https://keydris-mcp-demo.fly.dev/mcp`. The gateway releases only a
vault credential whose host/path scope covers that MCP origin, and evaluates its policy with the
same origin plus the tool name and parameters. No MCP-server enrollment identity or certificate
participates.

This controls which MCP server receives the PAT. The server's later
`GET https://api.github.com/user` call is trusted server behavior; governing that downstream use
would require routing the server's egress through Keydris. The legacy access-token fallback remains
unchanged.

## Setup

1. **Store the PAT.** On /vault, add an API key credential with the `ghp_…` value, then set its
   routing to:
   - host pattern: `keydris-mcp-demo.fly.dev`
   - optional path pattern: `/mcp`
   - injection: header `Authorization`, format `Bearer {value}`

   Leaving the injection blank also works — the gateway falls back to
   `Authorization: Bearer {value}` — but recording it makes the demo explicit.

   Only one vault entry may match that host/path, or the gateway refuses with
   `credential_not_found` rather than guessing between them.

2. **Configure.** `cp .env.example .env` and adjust if your control plane is not on
   `localhost:8080`.

3. **Run.** From the `node/` workspace root, so the library is built first:

```bash
npm install
npm run dev
```

4. **Point the proxy at it.** The authorize call needs `dst_addr` to be this server's `host:port`,
   e.g. `localhost:8787`. The proxy only authorizes hosts in its managed scope, so add it:

```bash
keydris proxy scope add localhost:8787
```

A destination outside the scope is passed through opaquely, so the proxy will not mint and inject a
KIT action token for its tool calls.

## Running it hosted

The build context is the `node/` workspace root — it has to span both the library and this example —
so deploy from there:

```bash
cd ../..    # the node/ workspace root
fly deploy
```

That yields a stable HTTPS hostname such as `keydris-mcp-demo.fly.dev`. Two things then have to move
off `localhost` together, or the demo half-works in a way that is tedious to diagnose:

- the proxy scope, to `<host>:443`
- the MCP connection's registered URL, to `https://<host>/mcp`

Remote HTTPS reaches the proxy as CONNECT + MITM rather than plain HTTP. No extra setup is needed:
`keydris run` already exports `NODE_EXTRA_CA_CERTS` and `SSL_CERT_FILE` for the child process.

## Getting policy to gate it

Connecting the server as an MCP connection (`POST /integrations/mcp` with
`url = https://<host>/mcp`) is what makes it addressable by policy. The handshake records
`connectedTo` and fills `capabilities` from `tools/list`, and the runtime route carries its selected
tool resources and connection identity.

Choose **Kit Reader** as the enforcement mode. Lifecycle and discovery methods such as `initialize`
and `tools/list` pass through without credential redemption. A `tools/call` for `github_whoami` is
policy-evaluated when the server redeems its connection-scoped action token.

## Gating the PAT itself

An integration rule decides whether `github_whoami` may run. A _credential_ rule decides,
separately, whether the PAT may be released for `POST keydris-mcp-demo.fly.dev/mcp`. The gateway
evaluates both before consuming the single-use token and revealing the secret, and answers
`policy_denied` if either rule refuses.

Set the credential rule to `reject` to see the split: the action can be allowed while the PAT
release is denied, and the tool returns the redemption failure instead of a GitHub identity.

## How the token is handled

`keydrisCredentials(reader)` from `@keydris/kit-reader/express` is the middleware, mounted in
[`src/index.ts`](src/index.ts). For each `tools/call`, the reader first looks at
`params._meta["keydris/kit_action_token"]`, then falls back to the configured legacy HTTP header.
For a KIT token it also sends the actual tool name and arguments; the gateway derives the registered
MCP URL from the token's connection. The legacy fallback still sends only `{ token }`. Every
redemption reveals a secret from the vault, while `initialize` and `tools/list` disclose nothing
that would justify one. A client with no token can therefore still connect and list the tool; it
finds out it needs one only when it asks for something that costs a secret.

The released credential is never stored. The MCP server and its transport are built per request in
stateless mode, so the secret lives on the stack of the call that was authorized for it and goes
away with the response. An MCP session would otherwise outlive the ~5 minute access token that
authorized it.

Everything that stops a credential arriving — a missing token, a refusal naming its code
(`credential_not_found`, `session_inactive`, `credential_unavailable`, …), an unreachable gateway —
comes back as a tool error saying so, rather than an HTTP failure the agent cannot read.

## Trying it without a control plane

Point `KEYDRIS_GATEWAY_URL` at any stub that answers

```json
{
  "credentials": [
    {
      "type": "header",
      "name": "Authorization",
      "prefix": "",
      "value": "Bearer ghp_…"
    }
  ]
}
```

and `GITHUB_API_BASE` at a stub `/user`. The server does not verify the token itself — that is the
gateway's job — so any string works as the bearer. Then:

```bash
curl -X POST http://localhost:8787/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"github_whoami","arguments":{},
        "_meta":{"keydris/kit_action_token":"anything"}}}'
```

The same call with the `_meta` block removed returns the redemption failure instead — which is the
whole point of the demo.

## Development

Run these from the `node/` workspace root:

```bash
npm run typecheck   # tsc --noEmit across both workspaces
npm test            # the library's suite
npm run build       # emit dist/ for both
npm start           # run the built server
```
