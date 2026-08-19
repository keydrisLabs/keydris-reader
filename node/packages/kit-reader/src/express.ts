import type { RequestHandler } from 'express';
import type { KitReader, Redemption } from './types.js';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      redemption?: Redemption;
    }
  }
}

/**
 * Turns the proxy's access token into the credential this server needs upstream
 * and leaves the result on `req.redemption`.
 *
 * Requests that call no tool are passed through with `req.redemption` unset:
 * `initialize` and `tools/list` cost nothing, so a client with no token can
 * still connect and see what is on offer. Everything that stops a credential
 * arriving lands as `{ ok: false, problem }` for the tool handler to report,
 * rather than as an HTTP failure the agent cannot read.
 */
export function keydrisCredentials(reader: KitReader): RequestHandler {
  return (req, _res, next) => {
    reader
      .redeem(req.body, { header: req.header(reader.tokenHeader) })
      .then((redemption) => {
        if (redemption) {
          req.redemption = redemption;
        }
        next();
      })
      .catch(next);
  };
}
