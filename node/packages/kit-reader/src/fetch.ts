import { applyCredentials } from './credentials.js';
import type { KitSpend, TargetMethod } from './types.js';

/**
 * The upstream response, or the reason no credentialed request could be made.
 * Upstream HTTP failures are not folded in: a 401 from the API is still an
 * `ok: true` result carrying that response, for the tool to interpret.
 */
export type KeydrisFetchResult =
  { ok: true; response: Response } | { ok: false; problem: string };

const TARGET_METHODS: ReadonlySet<string> = new Set([
  'GET',
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
  'HEAD',
  'OPTIONS',
] satisfies TargetMethod[]);

/**
 * Spends a KIT action token on one outbound call: derives the target from the
 * URL (hostname without port, path without query — the shape the gateway
 * matches vault entries and policy against), redeems, applies the released
 * credentials, and performs the fetch. The secret never leaves this call's
 * stack.
 *
 * Adapter-agnostic: pass the spend your adapter armed for the current request
 * (`kitSpendFrom(req)` for Express).
 */
export async function keydrisFetch(
  spend: KitSpend,
  input: string | URL,
  init?: RequestInit,
): Promise<KeydrisFetchResult> {
  const url = new URL(input);
  const method = (init?.method ?? 'GET').toUpperCase();
  if (!TARGET_METHODS.has(method)) {
    return {
      ok: false,
      problem: `The Keydris gateway cannot authorize the HTTP method ${method}.`,
    };
  }

  const redemption = await spend({
    host: url.hostname,
    path: url.pathname || '/',
    method: method as TargetMethod,
  });
  if (!redemption.ok) {
    return { ok: false, problem: redemption.problem };
  }

  const headers = new Headers(init?.headers);
  applyCredentials(redemption.credentials, url, headers);
  try {
    const response = await fetch(url, {
      ...init,
      method,
      headers,
      redirect: 'error',
    });
    redemption.reportOutcome?.({
      outcome: response.ok ? 'SUCCEEDED' : 'FAILED',
      provider_status: response.status,
    });
    return { ok: true, response };
  } catch (error) {
    redemption.reportOutcome?.({
      outcome: 'UNKNOWN',
      error_code: 'provider_transport_unknown',
    });
    throw error;
  }
}
