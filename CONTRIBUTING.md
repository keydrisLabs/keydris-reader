# Contributing to keydris-reader

Thanks for helping out. This repository holds two implementations of one library, Node and Python,
plus a sample server for each, and the thing that makes it unusual is that **the two must stay
byte-identical on the wire**. Most of the guidance below follows from that.

Questions and design discussion are welcome in [Discord](https://discord.gg/mHN8z7qYRV) or an
[issue](https://github.com/keydrisLabs/keydris-reader/issues). Vulnerabilities go through
[SECURITY.md](SECURITY.md) instead, never a public issue.

---

## The one rule specific to this repository

A `problem` string is read by an agent, not a human, so **the wording is part of the wire
contract.** `python/packages/kit-reader/tests/test_parity.py` provokes every refusal the Python
reader can produce, reads every `.ts` file in the Node `src/`, and asserts each string appears there
verbatim.

That means:

- A behavior change on one side needs the same change on the other, in the same pull request.
- A reworded failure message is a **breaking change**, not a copy edit.
- `KIT_ACTION_TOKEN_META_KEY` is a constant of the protocol and has its own test.

If you are only fixing a typo in a comment or a README, none of this applies.

---

## Repository layout

| Path | What it is |
| --- | --- |
| [`node/packages/kit-reader`](node/packages/kit-reader) | `@keydris/kit-reader`, published |
| [`node/examples/github-mcp-server`](node/examples/github-mcp-server) | Sample server (private, never published) |
| [`python/packages/kit-reader`](python/packages/kit-reader) | `keydris-kit-reader`, published |
| [`python/examples/github-mcp-server`](python/examples/github-mcp-server) | Sample server (never published) |

The split between library and sample is load-bearing. The library stays dependency-free and
framework-agnostic; anything framework-specific belongs in the sample or behind an optional adapter.

---

## Development setup

### Node

```bash
cd node
npm install         # workspaces: library + example
npm run typecheck   # tsc --noEmit in both
npm test            # node:test over packages/kit-reader/src/*.test.ts
npm run build       # library first, then example
npm run dev         # watch-run the example on :8787
```

### Python

```bash
cd python
uv sync --all-packages
uv run pytest
uv run mypy               # strict, floored at 3.10
uv run ruff check .
uv run ruff format --check .
uv run github-mcp-server  # the example, on :8788
```

Both samples read their configuration from `.env`:

```bash
cp examples/github-mcp-server/.env.example examples/github-mcp-server/.env
```

Neither needs a control plane to run. Point `KEYDRIS_GATEWAY_URL` and `GITHUB_API_BASE` at stubs,
as the sample READMEs describe.

---

## What CI will run

Every pull request runs two jobs, and they are the bar to clear locally:

| Job | Steps |
| --- | --- |
| **node** | `npm ci`, `typecheck`, `test`, `build`, `npm pack --dry-run` |
| **python** | matrix 3.10 / 3.13, then `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy`, `pytest`, `uv build`, `twine check` |

`npm pack --dry-run` and `twine check` are there on purpose: a bad `files` entry or a missing subpath
export should fail a pull request, not a release.

`uv sync --locked` means **commit `uv.lock`** when you change Python dependencies.

---

## Conventions

- **Zero runtime dependencies, in both libraries.** Python's default transport is stdlib `urllib`;
  anything else is injected through the `Transport` seam. Node uses the global `fetch`. New optional
  functionality goes behind an extra (`[mcp]`) or an optional peer (`express`), and the main entry
  point must never import it.
- **Typing is strict.** `tsc --noEmit` clean, and `mypy --strict` with `python_version = "3.10"` so
  newer-only typing cannot creep in.
- **Formatting is `ruff` on the Python side** (line length 100, rules `E,F,I,UP,B,SIM,RUF`). Match
  the surrounding style on the Node side.
- **Redemption never raises.** Anything that stops a credential arriving becomes a `Redemption`
  carrying a `problem`. If you find yourself adding a `throw` or a `raise` to the redemption path,
  that is the thing to reconsider.
- **Never widen a secret's reach.** No new logging of `credentials`, no new `repr` that could carry
  one, no caching of a `Redemption`.
- **Tests live next to what they test:** `src/*.test.ts` in Node, `tests/test_*.py` in Python, and
  the ported suites keep their docstring naming the Node file they mirror.

---

## Pull requests

1. Fork and branch: `git checkout -b feat/your-change`.
2. Make the change in **both languages** if it touches behavior on the wire.
3. Add or update tests. A new refusal needs a Python test *and* the Node string it matches.
4. Run the checks for the workspaces you touched.
5. Write a commit message that says what changed and why; the existing history uses
   `feat:` / `fix:` / `chore:` / `ci:` prefixes.
6. Open the pull request against `main`, and describe the behavior change, not just the diff.

Small, reviewable pull requests move faster than large ones. If you are planning something
structural, such as a new adapter or a change to the redemption body, open an issue or ask in
Discord first, so we can agree on the shape before you build it.

---

## Releasing

Maintainers only. The two libraries version independently through package-scoped tags:

```bash
# Node
cd node
npm version minor -w @keydris/kit-reader --no-git-tag-version
git commit -am "release: @keydris/kit-reader 0.2.0"
git tag kit-reader-v0.2.0 && git push origin main --follow-tags
```

```bash
# Python: edit version in packages/kit-reader/pyproject.toml, then
git tag kit-reader-py-v0.2.0 && git push origin main --follow-tags
```

Both workflows re-run the full checks, **refuse to publish if the tag and the manifest version
disagree**, and publish through GitHub OIDC trusted publishing: no npm token, no PyPI token, and a
provenance or PEP 740 attestation on every release. Both accept a manual `dry_run: true`.

---

## Licensing of contributions

This project is licensed under the [Apache License 2.0](LICENSE). By submitting a contribution you
agree that it is licensed under those same terms, including the patent grant in section 5, and that
you have the right to submit it. New source files should carry no separate license header; the
repository-level `LICENSE` and [`NOTICE`](NOTICE) cover them.

---

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). It applies to issues, pull
requests, and the Discord.
