import assert from 'node:assert/strict';
import { test } from 'node:test';
import { keydrisFetch } from './fetch.js';
import { createKitReader } from './redeem.js';
import type { ProviderOutcome } from './telemetry.js';

test('provider transport failures report UNKNOWN and never replay the provider', async () => {
  const originalFetch = globalThis.fetch;
  const reports: Omit<ProviderOutcome, 'receipt'>[] = [];
  let attempts = 0;
  globalThis.fetch = async (_url, init) => {
    attempts++;
    assert.equal(init?.redirect, 'error');
    throw new Error('connection lost after dispatch');
  };
  try {
    await assert.rejects(
      keydrisFetch(
        async () => ({
          ok: true,
          credentials: [
            {
              type: 'header',
              name: 'authorization',
              prefix: '',
              value: 'secret',
            },
          ],
          reportOutcome: (outcome) => reports.push(outcome),
        }),
        'https://provider.test/action',
      ),
    );
    assert.equal(attempts, 1);
    assert.deepEqual(reports, [
      { outcome: 'UNKNOWN', error_code: 'provider_transport_unknown' },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('installation keys require secure endpoints even with the legacy lab override', () => {
  assert.throws(() =>
    createKitReader({
      gatewayUrl: 'http://external.test/gateway/credentials',
      installationKey: 'machine-key',
      allowInsecureGatewayUrl: true,
    }),
  );
});
