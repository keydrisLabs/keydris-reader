"""The tool, and the one line that gives it a credential."""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from keydris_kit_reader import KitReader
from keydris_kit_reader.mcp import current_redemption, keydris_credentials
from keydris_kit_reader_github_demo.github import (
    GitHubError,
    GitHubUser,
    fetch_authenticated_user,
)

INSTRUCTIONS = (
    "Calls the GitHub API using a token the Keydris gateway releases for this "
    "call. No credential is configured on this server."
)


def build_server(reader: KitReader) -> MCPServer:
    """The middleware is the whole integration: it redeems each `tools/call` and
    scopes the result to that call, so the tool below reads a credential it never
    stored and cannot outlive."""
    mcp = MCPServer(
        name="keydris-github-demo",
        version="0.0.1",
        instructions=INSTRUCTIONS,
        middleware=[keydris_credentials(reader)],
    )

    @mcp.tool(
        name="github_whoami",
        title="GitHub: who am I",
        description="Returns the GitHub account the released personal access token belongs to.",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    async def github_whoami() -> GitHubUser:
        # Any exception raised here reaches the agent as an `isError` result whose
        # text is the message — which is how a refusal stays readable.
        redemption = current_redemption()
        if redemption is None:
            raise ToolError("No credential was released for this request.")
        if not redemption.ok:
            raise ToolError(redemption.problem)

        try:
            return await fetch_authenticated_user(redemption.credentials)
        except GitHubError as error:
            raise ToolError(
                f"GitHub rejected the released credential with {error.status}."
            ) from error
        except Exception as error:
            raise ToolError("The GitHub request could not be completed.") from error

    return mcp
