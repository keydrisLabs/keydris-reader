# keydris-reader

A library that lets an MCP server hold **no credential of its own** — and a sample
server built on it.

Instead of configuring a secret on the server, baking it into an image, or holding
it between requests, the server obtains the credential a tool needs at call time,
by redeeming the single-use, action-scoped KIT token the Keydris proxy injected
into the MCP request.

```
agent ──► proxy ──► POST /v1/runtime/mcp/kit-action-tokens ──► KIT action token
          proxy ──► POST /mcp
                    params._meta["keydris/kit_action_token"] = token
                                                            ──► the MCP server
                    the MCP server ──► POST /gateway/credentials
                                      {token, mcp}
                                   ◄── {credentials:[{type,name,prefix,value}]}
                    the MCP server ──► the upstream API  (credential applied)
```

The two pieces are kept separate on purpose:

- **The library** does the token handling — reading the action token out of the
  MCP request, redeeming it at the gateway, applying the released credential to
  the outbound call. Install it in any MCP server; it has no dependencies and no
  opinion about your HTTP framework.
- **The sample** is a complete server that uses it: one `github_whoami` tool
  backed by a GitHub PAT the server never stores. It is what to read, run, and
  copy from.

## Why it is shaped this way

- **Redemption is bound to the actual call.** The server sends the tool name and
  the exact arguments it was asked to run alongside the token, so the gateway
  evaluates policy against the call that is really about to happen. One KIT
  action token authorizes one action; a batch that reuses a token is refused.
- **Only `tools/call` costs a secret.** `initialize` and `tools/list` pass
  through untouched, so a client with no token can still connect and see what is
  on offer — it discovers it needs one only when it asks for something that
  reveals a credential.
- **Nothing outlives the request.** The library holds no state between calls, and
  the sample builds its MCP server and transport per request in stateless mode, so
  the released credential lives on the stack of the call that was authorized for
  it. A long-lived MCP session would otherwise outlive the short-lived token that
  authorized it — the one part a server has to get right for itself.
- **Failures are answers, not crashes.** A missing token, a gateway refusal
  naming its code, an unreachable gateway — each comes back as a readable tool
  error rather than an HTTP failure the agent has to guess at.

## Implementations

| Language | Library                                                          | Sample                                                                            | Status      |
| -------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------- | ----------- |
| Node/TS  | [`@keydris/kit-reader`](node/packages/kit-reader)                 | [`github-mcp-server`](node/examples/github-mcp-server)                             | Available   |
| Python   | `python/`                                                         | —                                                                                 | Coming soon |

Start with [`node/packages/kit-reader/README.md`](node/packages/kit-reader/README.md)
to put KIT reading into your own server, or
[`node/examples/github-mcp-server/README.md`](node/examples/github-mcp-server/README.md)
for setup, running it locally, deploying it, and wiring policy to gate both the
action and the credential release.

## Quick start

```bash
cd node
npm install
cp examples/github-mcp-server/.env.example examples/github-mcp-server/.env
npm run dev
```

The sample server listens on `:8787` and redeems against the gateway URL in that
`.env`. It can be exercised without a control plane at all — point
`KEYDRIS_GATEWAY_URL` and `GITHUB_API_BASE` at stubs, as described in
[the sample's README](node/examples/github-mcp-server/README.md#trying-it-without-a-control-plane).

## License

Not yet finalized. A `LICENSE` file will be added before this repository is made
public.
