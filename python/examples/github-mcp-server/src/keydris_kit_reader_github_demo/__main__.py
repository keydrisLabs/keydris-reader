"""`github-mcp-server`, or `python -m keydris_kit_reader_github_demo`."""

from __future__ import annotations

import uvicorn

from keydris_kit_reader_github_demo.app import app
from keydris_kit_reader_github_demo.config import config


def main() -> None:
    print(
        f"keydris-github-demo listening on {config.host}:{config.port}/mcp "
        f"— redeeming at {config.gateway_url}"
    )
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
