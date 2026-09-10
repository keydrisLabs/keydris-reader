import { keydrisFetch, type KitSpend } from '@keydris/kit-reader';
import { config } from './config.js';

export type GitHubUser = {
  login: string;
  name: string | null;
  htmlUrl: string;
  publicRepos: number;
};

export class GitHubError extends Error {
  constructor(readonly status: number) {
    super(`GitHub replied ${status}`);
  }
}

export class RedemptionRefused extends Error {}

/**
 * `GET /user` — the endpoint that answers "whose token is this?", which makes it
 * the clearest proof that the credential the gateway released is the PAT and that
 * it arrived intact.
 *
 * One tool call, one outbound request: `keydrisFetch` spends this call's token
 * for the credential this exact request needs, applies it, and sends it. The
 * secret never appears in tool code.
 */
export async function fetchAuthenticatedUser(
  spend: KitSpend,
): Promise<GitHubUser> {
  const result = await keydrisFetch(spend, new URL('/user', config.githubApiBase), {
    headers: {
      accept: 'application/vnd.github+json',
      'x-github-api-version': '2022-11-28',
      'user-agent': 'keydris-mcp-demo',
    },
  });
  if (!result.ok) {
    throw new RedemptionRefused(result.problem);
  }
  if (!result.response.ok) {
    throw new GitHubError(result.response.status);
  }

  const user = (await result.response.json()) as {
    login: string;
    name: string | null;
    html_url: string;
    public_repos: number;
  };
  return {
    login: user.login,
    name: user.name,
    htmlUrl: user.html_url,
    publicRepos: user.public_repos,
  };
}
