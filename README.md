# keydris-reader

A reference MCP server that holds **no credential of its own**.

It exposes one tool, `github_whoami`, and obtains the GitHub PAT that tool needs
at call time by redeeming the single-use, action-scoped KIT token the Keydris
proxy injected into the MCP request. Nothing secret is configured on the server,
baked into its image, or held between requests.

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

## Why it is shaped this way

- **Redemption is bound to the actual call.** The server sends the tool name and
  the exact arguments it was asked to run alongside the token, so the gateway
  evaluates policy against the call that is really about to happen. One KIT
  action token authorizes one action; a batch that reuses a token is refused.
- **Only `tools/call` costs a secret.** `initialize` and `tools/list` pass
  through untouched, so a client with no token can still connect and see what is
  on offer — it discovers it needs one only when it asks for something that
  reveals a credential.
- **Nothing outlives the request.** The MCP server and its transport are built
  per request in stateless mode, so the released credential lives on the stack of
  the call that was authorized for it. A long-lived MCP session would otherwise
  outlive the short-lived token that authorized it.
- **Failures are answers, not crashes.** A missing token, a gateway refusal
  naming its code, an unreachable gateway — each comes back as a readable tool
  error rather than an HTTP failure the agent has to guess at.

## Implementations

| Language | Path              | Status                    |
| -------- | ----------------- | ------------------------- |
| Node/TS  | [`node/`](node/)  | Available                 |
| Python   | `python/`         | Coming soon               |

Start with [`node/README.md`](node/README.md) for setup, running it locally,
deploying it, and wiring policy to gate both the action and the credential
release.

## Quick start

```bash
cd node
npm install
cp .env.example .env
npm run dev
```

The server listens on `:8787` and redeems against the gateway URL in `.env`.
It can be exercised without a control plane at all — point
`KEYDRIS_GATEWAY_URL` and `GITHUB_API_BASE` at stubs, as described in
[`node/README.md`](node/README.md#trying-it-without-a-control-plane).

## License

Not yet finalized. A `LICENSE` file will be added before this repository is made
public.
