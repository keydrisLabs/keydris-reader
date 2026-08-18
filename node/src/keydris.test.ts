import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { kitActionTokenFrom } from './keydris.js';

function toolCall(token: string, arguments_: Record<string, unknown> = {}) {
  return {
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
      name: 'github_whoami',
      arguments: arguments_,
      _meta: { 'keydris/kit_action_token': token },
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
});
