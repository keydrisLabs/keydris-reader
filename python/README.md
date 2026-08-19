# keydris-reader — Python workspace

Two separate things: the library any MCP server can install, and a sample server built on it.

| Workspace                                                  | What it is                                                                 |
| ---------------------------------------------------------- | -------------------------------------------------------------------------- |
| [`packages/kit-reader`](packages/kit-reader)               | **`keydris-kit-reader`** — the library. Zero runtime dependencies, framework-agnostic, with an optional adapter for the MCP Python SDK. This is the reusable piece. |
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

Read [`packages/kit-reader/README.md`](packages/kit-reader/README.md) to put KIT reading into your own
server, and [`examples/github-mcp-server/README.md`](examples/github-mcp-server/README.md) for vault
setup, proxy scope, and wiring policy.

This is the Python half of [`node/`](../node). The `_meta` key, the redemption body, and the failure
messages are identical in both, so a server written against either reads the same to the proxy, the
gateway, and the agent.

## Quick start

Needs [uv](https://docs.astral.sh/uv/) (`brew install uv`) and Python >= 3.10.

```bash
uv sync --all-packages
cp examples/github-mcp-server/.env.example examples/github-mcp-server/.env
uv run github-mcp-server
```

The demo listens on `127.0.0.1:8788` — 8788 rather than the Node demo's 8787, so both can run at
once — and redeems against the gateway URL in that `.env`. The example's README shows how to exercise
it against stubs, with no control plane at all.

## Commands

Run these from here; the workspace covers both members.

```bash
uv sync --all-packages   # install the library, the example, and the dev tools
uv run pytest            # the library's suite
uv run mypy              # strict, across the library and the example
uv run ruff check .      # lint
uv run ruff format .     # format
uv build --package keydris-kit-reader   # emit dist/ for the library alone
uv run github-mcp-server # run the example
```

`uv.lock` is committed, so CI and a fresh clone resolve to the same versions; `uv sync --locked`
fails rather than silently updating it.

Deployment lives in [`node/`](../node) only: the hosted demo
(`keydris-mcp-demo.fly.dev`) is the Node one, and a second Fly app would need its own registered MCP
connection URL and vault routing entry to be useful.

## Releasing the library

Only `packages/kit-reader` is published; the example carries the `Private :: Do Not Upload`
classifier, which PyPI refuses outright. A release is a version bump and a tag —
[`.github/workflows/release-python.yml`](../.github/workflows/release-python.yml) does the rest:

```bash
# edit version in packages/kit-reader/pyproject.toml, then:
git commit -am "release: keydris-kit-reader 0.2.0"
git tag kit-reader-py-v0.2.0
git push origin main --follow-tags
```

The tag is package-scoped (`kit-reader-py-*`) so this library and `@keydris/kit-reader` release
independently — the Node one answers to `kit-reader-v*`. The workflow re-runs mypy and the tests,
then refuses to publish if the tag and `pyproject.toml` disagree, so a mistyped tag fails loudly
instead of shipping the wrong version.

Publishing uses PyPI **trusted publishing**: the registry credential comes from GitHub's OIDC token
at run time, so there is no API token secret to rotate, and every release carries a PEP 740
attestation linking it back to the workflow run. That needs one setup step on pypi.org — adding a
*pending* trusted publisher for `keydris-kit-reader` with repository `keydrisLabs/keydris-reader`,
workflow `release-python.yml`, and environment `pypi-publish`. Unlike npm, no manual first upload is
required: the pending publisher creates the project on the first successful run.

Two differences from the npm release worth knowing:

- **PyPI has no dist-tags.** Where npm publishes a prerelease under `next`, PEP 440 does the same job
  by version alone: `pip install keydris-kit-reader` skips `0.2.0rc1` unless asked with `--pre`. The
  workflow marks the GitHub release as a prerelease and nothing else changes.
- **Versions are immutable and unrecyclable.** A published version can be yanked but never replaced,
  so the dry run matters. Run the workflow manually from the Actions tab with `dry_run: true` to
  build, inspect, and validate the artifacts without publishing.
