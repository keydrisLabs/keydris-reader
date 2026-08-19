import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { callsATool, kitActionTokenFrom } from './token.js';

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

void describe('KIT action-token extraction', () => {
  void it('binds redemption to the actual tool call and GitHub request', () => {
    const result = kitActionTokenFrom(
      toolCall('action-token', { verbose: true }),
    );

    assert.equal(result.token, 'action-token');
    assert.deepEqual(result.context, {
      mcp: {
        method: 'tools/call',
        action_name: 'github_whoami',
        parameters: { verbose: true },
      },
    });
  });

  void it('rejects a batch that tries to reuse one action token', () => {
    const result = kitActionTokenFrom([
      toolCall('action-token'),
      toolCall('action-token'),
    ]);

    assert.equal(
      result.problem,
      'A KIT action token can authorize only one MCP action per request.',
    );
  });

  void it('strips a Bearer scheme from the injected token', () => {
    assert.equal(kitActionTokenFrom(toolCall('Bearer action-token')).token, 'action-token');
  });

  void it('finds nothing in a body that carries no token', () => {
    assert.deepEqual(kitActionTokenFrom(toolCall()), {});
    assert.deepEqual(
      kitActionTokenFrom({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      {},
    );
  });

  void it('reports a malformed token rather than ignoring it', () => {
    const call = toolCall();
    const result = kitActionTokenFrom({
      ...call,
      params: { ...call.params, _meta: { 'keydris/kit_action_token': 42 } },
    });

    assert.equal(result.problem, 'The Keydris KIT action token is malformed.');
  });

  void it('reports a tokenized call whose name or arguments are malformed', () => {
    const call = toolCall('action-token');

    assert.equal(
      kitActionTokenFrom({ ...call, params: { ...call.params, name: '' } })
        .problem,
      'The tokenized MCP tool call is malformed.',
    );
    assert.equal(
      kitActionTokenFrom({ ...call, params: { ...call.params, arguments: [] } })
        .problem,
      'The tokenized MCP tool call is malformed.',
    );
  });

  void it('recognizes which bodies cost a secret', () => {
    assert.equal(callsATool(toolCall('action-token')), true);
    assert.equal(callsATool([{ method: 'tools/list' }, toolCall()]), true);
    assert.equal(callsATool({ method: 'initialize' }), false);
    assert.equal(callsATool(undefined), false);
  });
});
