import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createReaderTelemetry,
  observeTool,
  readerApiUrl,
} from './telemetry.js';

test('retries delivery with the same ID and observes isError rather than HTTP status', async () => {
  const bodies: string[] = [];
  const telemetry = createReaderTelemetry({
    apiUrl: 'https://keydris.test/',
    apiKey: 'machine',
    retryDelayMs: 0,
    fetch: async (_url, init) => {
      assert.equal(
        new Headers(init?.headers).get('authorization'),
        'Bearer machine',
      );
      assert.equal(init?.redirect, 'error');
      bodies.push(String(init?.body));
      return new Response(null, { status: bodies.length === 1 ? 503 : 200 });
    },
  });
  const result = { isError: true, content: [{ text: 'secret result' }] };
  assert.equal(
    await observeTool(telemetry, 'weather', undefined, async () => result),
    result,
  );
  await telemetry.flush();
  assert.equal(bodies[0], bodies[1]);
  assert.equal(JSON.parse(bodies[2]).outcome, 'FAILED');
  assert.ok(!bodies.join('').includes('secret result'));
  await telemetry.close();
});

test('handler exceptions propagate while completion is reported', async () => {
  const bodies: string[] = [];
  const telemetry = createReaderTelemetry({
    apiUrl: 'https://keydris.test',
    apiKey: 'key',
    fetch: async (_url, init) => {
      bodies.push(String(init?.body));
      return new Response(null, { status: 200 });
    },
  });
  await assert.rejects(
    observeTool(telemetry, 'weather', undefined, async () => {
      throw new Error('private details');
    }),
  );
  await telemetry.flush();
  assert.equal(JSON.parse(bodies[1]).error_code, 'handler_exception');
  assert.ok(!bodies.join('').includes('private details'));
  await telemetry.close();
});

test('refuses unsafe telemetry endpoints', () => {
  assert.throws(() => readerApiUrl('http://external.test'));
  assert.throws(() => readerApiUrl('https://name:secret@keydris.test'));
});
