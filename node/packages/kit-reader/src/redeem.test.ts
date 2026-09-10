import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createKitReader } from './redeem.js';

const GATEWAY = 'https://gateway.test/gateway/credentials';

const RELEASED = [
  {
    type: 'header' as const,
    name: 'Authorization',
    prefix: '',
    value: 'Bearer ghp_x',
  },
];

/** Records what the gateway was sent and answers with a canned response. */
function gatewayStub(
  answer: { status?: number; body?: unknown } | { throws: true },
) {
  const calls: { url: string; body: unknown }[] = [];
  const fetch: typeof globalThis.fetch = async (input, init) => {
    calls.push({
      url: String(input),
      body: JSON.parse(String(init?.body)),
    });
    if ('throws' in answer) {
      throw new TypeError('fetch failed');
    }
    return new Response(JSON.stringify(answer.body ?? {}), {
      status: answer.status ?? 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  return { fetch, calls };
}

function toolCall(token?: string, arguments_: Record<string, unknown> = {}) {
  return {
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
      name: 'github_whoami',
      arguments: arguments_,
      ...(token ? { _meta: { 'keydris/kit_action_token': token } } : {}),
    },
  };
}

const TARGET = { host: 'api.github.com', path: '/user', method: 'GET' as const };

void describe('redemption', () => {
  void it('sends the token with the call it authorizes and its target, and returns the credentials', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    const redemption = await reader.redeem(
      toolCall('action-token', { verbose: true }),
      { target: TARGET },
    );

    assert.deepEqual(redemption, { ok: true, credentials: RELEASED });
    assert.equal(gateway.calls.length, 1);
    assert.equal(gateway.calls[0].url, GATEWAY);
    assert.deepEqual(gateway.calls[0].body, {
      token: 'action-token',
      mcp: {
        method: 'tools/call',
        action_name: 'github_whoami',
        parameters: { verbose: true },
      },
      target: TARGET,
    });
  });

  void it('refuses a tokenized call that names no downstream target', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    const redemption = await reader.redeem(toolCall('action-token'));

    assert.deepEqual(redemption, {
      ok: false,
      problem:
        'A KIT action token redemption needs the downstream target (host, path, method) of the request it authorizes.',
    });
    assert.equal(gateway.calls.length, 0);
  });

  void it('costs nothing for initialize and tools/list', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    assert.equal(await reader.redeem({ method: 'initialize' }), undefined);
    assert.equal(
      await reader.redeem({ method: 'tools/list' }, { header: 'Bearer t' }),
      undefined,
    );
    assert.equal(gateway.calls.length, 0);
  });

  void it('falls back to the configured header, sending the token alone', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({
      gatewayUrl: GATEWAY,
      tokenHeader: 'X-Keydris-Token',
      fetch: gateway.fetch,
    });

    assert.equal(reader.tokenHeader, 'x-keydris-token');
    const redemption = await reader.redeem(toolCall(), {
      header: 'Bearer header-token',
    });

    assert.deepEqual(redemption, { ok: true, credentials: RELEASED });
    assert.deepEqual(gateway.calls[0].body, { token: 'header-token' });
  });

  void it('refuses a request whose action and header tokens disagree', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    const redemption = await reader.redeem(toolCall('action-token'), {
      header: 'other-token',
    });

    assert.deepEqual(redemption, {
      ok: false,
      problem:
        'The MCP request contains conflicting Keydris action and header tokens.',
    });
    assert.equal(gateway.calls.length, 0);
  });

  void it('names the header it looked on when no token arrived at all', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({
      gatewayUrl: GATEWAY,
      tokenHeader: 'x-keydris-token',
      fetch: gateway.fetch,
    });

    const redemption = await reader.redeem(toolCall());

    assert.deepEqual(redemption, {
      ok: false,
      problem:
        'No Keydris KIT action token in params._meta["keydris/kit_action_token"] or on the x-keydris-token header, so there is nothing to exchange for a credential.',
    });
    assert.equal(gateway.calls.length, 0);
  });

  void it('passes a malformed-token problem through without calling the gateway', async () => {
    const gateway = gatewayStub({ body: { credentials: RELEASED } });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    const redemption = await reader.redeem([
      toolCall('action-token'),
      toolCall('action-token'),
    ]);

    assert.deepEqual(redemption, {
      ok: false,
      problem:
        'A KIT action token can authorize only one MCP action per request.',
    });
    assert.equal(gateway.calls.length, 0);
  });

  void it('reports a refusal by the code the gateway named', async () => {
    const gateway = gatewayStub({
      status: 403,
      body: { error: { code: 'policy_denied' } },
    });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    assert.deepEqual(await reader.redeem(toolCall('action-token'), { target: TARGET }), {
      ok: false,
      problem: 'The Keydris gateway refused: policy_denied.',
    });
  });

  void it('falls back to the status when the refusal carries no code', async () => {
    const gateway = gatewayStub({ status: 502, body: {} });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    assert.deepEqual(await reader.redeem(toolCall('action-token'), { target: TARGET }), {
      ok: false,
      problem: 'The Keydris gateway refused: HTTP 502.',
    });
  });

  void it('reports an empty release rather than pretending it succeeded', async () => {
    const gateway = gatewayStub({ body: { credentials: [] } });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    assert.deepEqual(await reader.redeem(toolCall('action-token'), { target: TARGET }), {
      ok: false,
      problem: 'The Keydris gateway released nothing.',
    });
  });

  void it('reports an unreachable gateway instead of rejecting', async () => {
    const gateway = gatewayStub({ throws: true });
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

    assert.deepEqual(await reader.redeem(toolCall('action-token'), { target: TARGET }), {
      ok: false,
      problem: 'The Keydris gateway could not be reached.',
    });
  });

  void it('refuses a release whose envelopes are not the shape the gateway publishes', async () => {
    for (const credentials of [
      [{ type: 'cookie', name: 'session', prefix: '', value: 's' }],
      [{ type: 'header', name: '', prefix: '', value: 's' }],
      [{ type: 'header', name: 'Authorization', prefix: '', value: 42 }],
      [RELEASED[0], { type: 'header' }],
      ['not an envelope'],
    ]) {
      const gateway = gatewayStub({ body: { credentials } });
      const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: gateway.fetch });

      assert.deepEqual(
        await reader.redeem(toolCall('action-token'), { target: TARGET }),
        {
          ok: false,
          problem:
            'The Keydris gateway returned a credential in a shape this reader does not recognize.',
        },
      );
    }
  });

  void it('bounds the redemption with an abort signal so a hung gateway cannot hang the tool call', async () => {
    let signal: AbortSignal | null | undefined;
    const fetchSpy: typeof globalThis.fetch = async (_input, init) => {
      signal = init?.signal;
      return new Response(JSON.stringify({ credentials: RELEASED }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };
    const reader = createKitReader({ gatewayUrl: GATEWAY, fetch: fetchSpy });

    const redemption = await reader.redeem(toolCall('action-token'), {
      target: TARGET,
    });

    assert.deepEqual(redemption, { ok: true, credentials: RELEASED });
    assert.ok(signal instanceof AbortSignal);
  });
});

void describe('gateway URL validation', () => {
  void it('refuses a URL that could not receive a token', () => {
    assert.throws(
      () => createKitReader({ gatewayUrl: 'file:///etc/passwd' }),
      /http\(s\)/,
    );
    assert.throws(() => createKitReader({ gatewayUrl: 'not a url' }), /http\(s\)/);
  });

  void it('refuses plaintext http to a non-loopback host by default', () => {
    assert.throws(
      () => createKitReader({ gatewayUrl: 'http://gateway.internal/x' }),
      /plaintext http/,
    );
  });

  void it('accepts loopback http, and non-loopback only when explicitly allowed', () => {
    for (const url of [
      'http://localhost:8080/gateway/credentials',
      'http://127.0.0.1:8080/gateway/credentials',
      'http://[::1]:8080/gateway/credentials',
    ]) {
      assert.ok(createKitReader({ gatewayUrl: url }));
    }
    assert.ok(
      createKitReader({
        gatewayUrl: 'http://gateway.internal/x',
        allowInsecureGatewayUrl: true,
      }),
    );
  });
});
