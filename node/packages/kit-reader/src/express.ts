import type { RequestHandler, Request } from 'express';
import type { KitReader, KitSpend } from './types.js';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      kitSpend?: KitSpend;
    }
  }
}

/**
 * Arms each request with a one-shot spend of the token the Keydris proxy
 * injected (or the legacy header fallback).
 *
 * The gateway redeems a KIT action token only together with the downstream
 * target (host, path, method) of the request it authorizes — which is known
 * inside the tool at fetch time, not when the MCP request arrives. So this
 * middleware does not redeem: it leaves `req.kitSpend` for the tool to call on
 * the one outbound request it makes (most simply through `keydrisFetch`).
 *
 * Requests that call no tool still pass through and their spend refuses with a
 * readable problem: `initialize` and `tools/list` cost nothing, so a client
 * with no token can still connect and see what is on offer. Everything that
 * stops a credential arriving lands as `{ ok: false, problem }` for the tool
 * handler to report, rather than as an HTTP failure the agent cannot read.
 */
export function keydrisCredentials(reader: KitReader): RequestHandler {
  return (req, _res, next) => {
    const body: unknown = req.body;
    const header = req.header(reader.tokenHeader);

    let spent = false;
    req.kitSpend = async (target) => {
      if (spent) {
        return {
          ok: false,
          problem:
            'The KIT action token for this request was already spent: one token authorizes one outbound call.',
        };
      }
      spent = true;
      return (
        (await reader.redeem(body, { header, target })) ?? {
          ok: false,
          problem:
            'This MCP request calls no tool, so there is no action token to redeem.',
        }
      );
    };
    next();
  };
}

/**
 * The spend `keydrisCredentials` armed for the current request. Never
 * `undefined`: when the middleware is not registered the caller gets a
 * readable problem instead of a crash.
 */
export function kitSpendFrom(req: Pick<Request, 'kitSpend'>): KitSpend {
  return (
    req.kitSpend ??
    (async () => ({
      ok: false,
      problem:
        'The Keydris kit reader middleware is not armed for this request.',
    }))
  );
}
