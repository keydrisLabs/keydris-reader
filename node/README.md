# keydris-reader — Node workspaces

Two separate things: the library any MCP server can install, and a sample server built on it.

| Workspace                                              | What it is                                                                 |
| ------------------------------------------------------ | -------------------------------------------------------------------------- |
| [`packages/kit-reader`](packages/kit-reader)           | **`@keydris/kit-reader`** — the library. Zero runtime dependencies, framework-agnostic, with an optional Express adapter. This is the reusable piece. |
| [`examples/github-mcp-server`](examples/github-mcp-server) | A complete MCP server built on it: one `github_whoami` tool, no credential of its own. This is what to copy from. |

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

Read [`packages/kit-reader/README.md`](packages/kit-reader/README.md) to put KIT reading into your
own server, and [`examples/github-mcp-server/README.md`](examples/github-mcp-server/README.md) for
vault setup, proxy scope, deploying, and wiring policy.

## Quick start

```bash
npm install
cp examples/github-mcp-server/.env.example examples/github-mcp-server/.env
npm run dev
```

The demo listens on `:8787` and redeems against the gateway URL in that `.env`. The example's
README shows how to exercise it against stubs, with no control plane at all.

## Commands

Run these from here; they fan out across both workspaces, building the library first because the
example resolves it through the workspace symlink to its `dist/`.

```bash
npm run build       # library, then example
npm run typecheck   # tsc --noEmit in both
npm test            # the library's suite
npm run dev         # watch-run the example
npm start           # run the built example
```

Deployment ([`Dockerfile`](Dockerfile), [`fly.toml`](fly.toml)) lives here rather than in the
example, because the build context has to span both workspaces:

```bash
fly deploy
```
