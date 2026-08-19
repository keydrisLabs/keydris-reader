import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { applyCredentials } from './credentials.js';

void describe('credential application', () => {
  void it('puts a header credential on the outbound headers, prefix included', () => {
    const url = new URL('https://api.github.com/user');
    const headers = new Headers();

    applyCredentials(
      [
        {
          type: 'header',
          name: 'Authorization',
          prefix: 'Bearer ',
          value: 'ghp_secret',
        },
      ],
      url,
      headers,
    );

    assert.equal(headers.get('authorization'), 'Bearer ghp_secret');
    assert.equal(url.search, '');
  });

  void it('puts a query credential on the outbound URL', () => {
    const url = new URL('https://example.test/v1/thing?page=2');
    const headers = new Headers();

    applyCredentials(
      [{ type: 'query', name: 'api_key', prefix: '', value: 'k_secret' }],
      url,
      headers,
    );

    assert.equal(url.searchParams.get('api_key'), 'k_secret');
    assert.equal(url.searchParams.get('page'), '2');
    assert.equal([...headers.keys()].length, 0);
  });

  void it('applies every released credential', () => {
    const url = new URL('https://example.test/');
    const headers = new Headers();

    applyCredentials(
      [
        { type: 'header', name: 'Authorization', prefix: 'Bearer ', value: 'a' },
        { type: 'header', name: 'X-Tenant', prefix: '', value: 'b' },
        { type: 'query', name: 'key', prefix: 'v1_', value: 'c' },
      ],
      url,
      headers,
    );

    assert.equal(headers.get('authorization'), 'Bearer a');
    assert.equal(headers.get('x-tenant'), 'b');
    assert.equal(url.searchParams.get('key'), 'v1_c');
  });
});
