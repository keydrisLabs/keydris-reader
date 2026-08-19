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

/**
 * The call the token was minted for. Sent alongside the token so the gateway
 * evaluates policy against the action that is really about to happen.
 */
export type KitActionContext = {
  mcp: {
    method: 'tools/call';
    action_name: string;
    parameters: Record<string, unknown>;
  };
};

/** What `kitActionTokenFrom` found in a JSON-RPC body. */
export type TokenLookup = {
  token?: string;
  context?: KitActionContext;
  problem?: string;
};

export type KitReaderOptions = {
  /** The control plane's redemption endpoint, e.g. `https://api.keydris.com/gateway/credentials`. */
  gatewayUrl: string;

  /**
   * Legacy `/agent/authorize` header accepted as a fallback, lowercased.
   * Defaults to `authorization`. `mcp_kit_reader` requests carry their
   * action-scoped token in MCP `params._meta` instead.
   */
  tokenHeader?: string;

  /** Injectable for tests and for servers that route egress through their own client. */
  fetch?: typeof globalThis.fetch;
};

export type KitReader = {
  /** The header this reader falls back to, lowercased. */
  readonly tokenHeader: string;

  /** Whether this JSON-RPC body invokes a tool — i.e. whether it would cost a secret. */
  callsATool(body: unknown): boolean;

  /**
   * Turns the token carried by an MCP request into the credentials the server
   * needs upstream.
   *
   * Resolves to `undefined` when the body calls no tool: `initialize` and
   * `tools/list` disclose nothing that would justify revealing a secret, so
   * there is nothing to redeem. Otherwise it resolves to a `Redemption` —
   * success or a readable problem. It does not reject.
   */
  redeem(
    body: unknown,
    source?: { header?: string },
  ): Promise<Redemption | undefined>;
};
