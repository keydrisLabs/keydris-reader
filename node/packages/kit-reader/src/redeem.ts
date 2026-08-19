import { callsATool, kitActionTokenFrom, tokenFrom } from './token.js';
import type {
  CredentialEnvelope,
  KitActionContext,
  KitReader,
  KitReaderOptions,
  Redemption,
} from './types.js';

/**
 * A reader bound to one gateway. Construct it once at startup and hand it the
 * body of each MCP request; it holds no per-request state, so a single instance
 * serves every connection.
 */
export function createKitReader(options: KitReaderOptions): KitReader {
  const { gatewayUrl } = options;
  const tokenHeader = (options.tokenHeader ?? 'authorization')
    .trim()
    .toLowerCase();
  const doFetch = options.fetch ?? globalThis.fetch;

  async function exchange(
    token: string,
    context?: KitActionContext,
  ): Promise<Redemption> {
    let response: Response;
    try {
      response = await doFetch(gatewayUrl, {
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

  return {
    tokenHeader,

    callsATool,

    /**
     * Only `tools/call` is touched. Every redemption reveals a secret from the
     * vault, and `initialize`/`tools/list` disclose nothing that would justify
     * one — so a client with no token at all can still connect and see what is
     * on offer, and finds out it needs one only when it asks for something that
     * costs a secret.
     */
    async redeem(body, source) {
      if (!callsATool(body)) {
        return undefined;
      }

      const kitActionToken = kitActionTokenFrom(body);
      if (kitActionToken.problem) {
        return { ok: false, problem: kitActionToken.problem };
      }

      const headerToken = tokenFrom(source?.header);
      if (
        kitActionToken.token &&
        headerToken &&
        kitActionToken.token !== headerToken
      ) {
        return {
          ok: false,
          problem:
            'The MCP request contains conflicting Keydris action and header tokens.',
        };
      }

      const token = kitActionToken.token ?? headerToken;
      if (!token) {
        return {
          ok: false,
          problem: `No Keydris KIT action token in params._meta["keydris/kit_action_token"] or on the ${tokenHeader} header, so there is nothing to exchange for a credential.`,
        };
      }

      return exchange(token, kitActionToken.context);
    },
  };
}
