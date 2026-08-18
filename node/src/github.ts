import { config } from './config.js';
import { applyCredentials, type CredentialEnvelope } from './keydris.js';

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

/**
 * `GET /user` — the endpoint that answers "whose token is this?", which makes it
 * the clearest proof that the credential the gateway released is the PAT and that
 * it arrived intact.
 */
export async function fetchAuthenticatedUser(
  credentials: CredentialEnvelope[],
): Promise<GitHubUser> {
  const url = new URL('/user', config.githubApiBase);
  const headers = new Headers({
    accept: 'application/vnd.github+json',
    'x-github-api-version': '2022-11-28',
    'user-agent': 'keydris-mcp-demo',
  });
  applyCredentials(credentials, url, headers);

  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new GitHubError(response.status);
  }

  const user = (await response.json()) as {
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
