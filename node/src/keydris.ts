import type { RequestHandler } from 'express';
import { config } from './config.js';

/** Mirrors the gateway's `credentialEnvelopeSchema`. */
export type CredentialEnvelope = {
  type: 'header' | 'query';
  name: string;
  prefix: string;
  value: string;
};

/**
 * A redemption never rejects: anything that stops a credential arriving is
 * something the agent should be told about in the tool result, not an HTTP
 * failure that leaves it guessing. `problem` is that explanation.
 */
export type Redemption =
  | { ok: true; credentials: CredentialEnvelope[] }
  | { ok: false; problem: string };

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      redemption?: Redemption;
    }
  }
}

/**
 * Accepts both `Bearer <jwt>` and a bare token, since the header the proxy uses is
 * configurable and only the default carries a scheme.
 */
function tokenFrom(raw: string | undefined): string | undefined {
  const value = raw?.trim();
  if (!value) {
    return undefined;
  }
  return /^bearer\s+/i.test(value) ? value.replace(/^bearer\s+/i, '') : value;
}

type KitActionContext = {
  mcp: {
    method: 'tools/call';
    action_name: string;
    parameters: Record<string, unknown>;
  };
};

type TokenLookup = {
  token?: string;
  context?: KitActionContext;
  problem?: string;
};

/**
 * Reads the action-scoped token injected by an `mcp_kit_reader` proxy and the
 * exact tool arguments it authorized. Batched tokenized actions are refused:
 * one KIT action token can be redeemed for one action only.
 */
export function kitActionTokenFrom(body: unknown): TokenLookup {
  const messages = Array.isArray(body) ? body : [body];
  let lookup: TokenLookup = {};

  for (const message of messages) {
    if ((message as { method?: string })?.method !== 'tools/call') {
      continue;
    }
    const params = (message as { params?: unknown }).params;
    const meta =
      params && typeof params === 'object'
        ? (params as { _meta?: unknown })._meta
        : undefined;
    const raw =
      meta && typeof meta === 'object'
        ? (meta as Record<string, unknown>)['keydris/kit_action_token']
        : undefined;
    if (raw === undefined) {
      continue;
    }
    const token = typeof raw === 'string' ? tokenFrom(raw) : undefined;
    if (!token) {
      return { problem: 'The Keydris KIT action token is malformed.' };
    }
    if (lookup.token) {
      return {
        problem:
          'A KIT action token can authorize only one MCP action per request.',
      };
    }
    const call = params as {
      name?: unknown;
      arguments?: unknown;
    };
    if (
      typeof call.name !== 'string' ||
      !call.name ||
      (call.arguments !== undefined &&
        (typeof call.arguments !== 'object' ||
          call.arguments === null ||
          Array.isArray(call.arguments)))
    ) {
      return { problem: 'The tokenized MCP tool call is malformed.' };
    }
    lookup = {
      token,
      context: {
        mcp: {
          method: 'tools/call',
          action_name: call.name,
          parameters: (call.arguments ?? {}) as Record<string, unknown>,
        },
      },
    };
  }
  return lookup;
}

async function redeem(
  token: string,
  context?: KitActionContext,
): Promise<Redemption> {
  let response: Response;
  try {
    response = await fetch(config.gatewayUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(context ? { token, ...context } : { token }),
    });
  } catch {
    return { ok: false, problem: 'The Keydris gateway could not be reached.' };
  }

  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const code = (body as { error?: { code?: string } })?.error?.code;
    return {
      ok: false,
      problem: `The Keydris gateway refused: ${code ?? `HTTP ${response.status}`}.`,
    };
  }

  const { credentials } = body as { credentials?: CredentialEnvelope[] };
  if (!credentials?.length) {
    return { ok: false, problem: 'The Keydris gateway released nothing.' };
  }
  return { ok: true, credentials };
}

/** Whether the JSON-RPC body — one message or a batch — invokes a tool. */
function callsATool(body: unknown): boolean {
  const messages = Array.isArray(body) ? body : [body];
  return messages.some(
    (message) => (message as { method?: string })?.method === 'tools/call',
  );
}

/**
 * Turns the proxy's access token into the credential this server needs upstream.
 *
 * Only `tools/call` is touched. Every redemption reveals a secret from the vault,
 * and `initialize`/`tools/list` disclose nothing that would justify one — so a
 * client with no token at all can still connect and see what is on offer, and
 * finds out it needs one only when it asks for something that costs a secret.
 */
export const keydrisCredentials: RequestHandler = (req, _res, next) => {
  if (!callsATool(req.body)) {
    next();
    return;
  }

  const kitActionToken = kitActionTokenFrom(req.body);
  if (kitActionToken.problem) {
    req.redemption = { ok: false, problem: kitActionToken.problem };
    next();
    return;
  }

  const headerToken = tokenFrom(req.header(config.tokenHeader));
  if (
    kitActionToken.token &&
    headerToken &&
    kitActionToken.token !== headerToken
  ) {
    req.redemption = {
      ok: false,
      problem:
        'The MCP request contains conflicting Keydris action and header tokens.',
    };
    next();
    return;
  }

  const token = kitActionToken.token ?? headerToken;
  if (!token) {
    req.redemption = {
      ok: false,
      problem: `No Keydris KIT action token in params._meta["keydris/kit_action_token"] or on the ${config.tokenHeader} header, so there is nothing to exchange for a credential.`,
    };
    next();
    return;
  }

  redeem(token, kitActionToken.context)
    .then((redemption) => {
      req.redemption = redemption;
      next();
    })
    .catch(next);
};

/** Applies released credentials to an outbound request, in place. */
export function applyCredentials(
  credentials: CredentialEnvelope[],
  url: URL,
  headers: Headers,
): void {
  for (const credential of credentials) {
    const value = `${credential.prefix}${credential.value}`;
    if (credential.type === 'query') {
      url.searchParams.set(credential.name, value);
    } else {
      headers.set(credential.name, value);
    }
  }
}
