import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { fetchAuthenticatedUser, GitHubError } from './github.js';
import type { Redemption } from './keydris.js';

const outputSchema = {
  login: z.string(),
  name: z.string().nullable(),
  htmlUrl: z.string(),
  publicRepos: z.number(),
};

function failed(message: string) {
  return { content: [{ type: 'text' as const, text: message }], isError: true };
}

/**
 * A server bound to one request's redemption. Building it per request keeps the
 * released secret on the stack of the call that was authorized for it, rather than
 * in anything that outlives the request.
 */
export function createServer(redemption: Redemption | undefined): McpServer {
  const server = new McpServer(
    { name: 'keydris-github-demo', version: '0.0.1' },
    {
      instructions:
        'Calls the GitHub API using a token the Keydris gateway releases for this session. No credential is configured on this server.',
    },
  );

  server.registerTool(
    'github_whoami',
    {
      title: 'GitHub: who am I',
      description:
        'Returns the GitHub account the released personal access token belongs to.',
      outputSchema,
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async () => {
      if (!redemption?.ok) {
        return failed(
          redemption?.problem ?? 'No credential was released for this request.',
        );
      }

      try {
        const user = await fetchAuthenticatedUser(redemption.credentials);
        return {
          content: [
            {
              type: 'text' as const,
              text: `Authenticated as ${user.login}${user.name ? ` (${user.name})` : ''}, ${user.publicRepos} public repos.`,
            },
          ],
          structuredContent: user,
        };
      } catch (error) {
        if (error instanceof GitHubError) {
          return failed(
            `GitHub rejected the released credential with ${error.status}.`,
          );
        }
        return failed('The GitHub request could not be completed.');
      }
    },
  );

  return server;
}
