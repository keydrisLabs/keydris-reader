import { randomUUID } from 'node:crypto';

export type ReaderEvent = {
  schema_version: 1;
  event_id: string;
  invocation_id: string;
  phase: 'started' | 'completed';
  method: 'tools/call' | 'resources/read';
  action_name: string;
  occurred_at: string;
  action_token?: string;
  outcome?: 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'UNKNOWN';
  error_code?:
    'tool_error' | 'handler_exception' | 'cancelled' | 'redemption_failed';
  duration_ms?: number;
};
export type ProviderOutcome = {
  receipt: string;
  outcome: 'SUCCEEDED' | 'FAILED' | 'UNKNOWN';
  provider_status?: number;
  error_code?: string;
};

export interface ReaderTelemetry {
  event(event: ReaderEvent): void;
  outcome(outcome: ProviderOutcome): void;
  start(): void;
  close(): Promise<void>;
  flush(timeoutMs?: number): Promise<void>;
}

/** URL configuration, never an MCP request, determines where the machine key goes. */
export function readerApiUrl(raw: string): URL {
  const url = new URL(raw.endsWith('/') ? raw : `${raw}/`);
  if (url.username || url.password || url.search || url.hash)
    throw new Error(
      'KEYDRIS_API_URL cannot contain credentials, query or fragment',
    );
  const loopback =
    url.hostname === 'localhost' ||
    url.hostname === '[::1]' ||
    /^127(?:\.\d{1,3}){3}$/.test(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback))
    throw new Error('KEYDRIS_API_URL must use HTTPS (except loopback)');
  return url;
}

/** Bounded best-effort delivery. The queue retries telemetry only, never tool execution. */
export function createReaderTelemetry(options: {
  apiUrl: string;
  apiKey: string;
  fetch?: typeof fetch;
  onDropped?: () => void;
  timeoutMs?: number;
  retryDelayMs?: number;
}): ReaderTelemetry {
  const base = readerApiUrl(options.apiUrl);
  const doFetch = options.fetch ?? globalThis.fetch;
  const queue: { path: string; body: unknown }[] = [];
  let pending: Promise<void> | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;
  let closed = false;
  const dropped = () => {
    try {
      options.onDropped?.();
    } catch {
      /* Reporting must not affect a tool. */
    }
  };
  async function send(item: { path: string; body: unknown }) {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await doFetch(new URL(item.path, base), {
          method: 'POST',
          redirect: 'error',
          headers: {
            'content-type': 'application/json',
            authorization: `Bearer ${options.apiKey}`,
          },
          body: JSON.stringify(item.body),
          signal: AbortSignal.timeout(options.timeoutMs ?? 3000),
        });
        await response.body?.cancel();
        if (response.ok) return;
        if (response.status < 500 && response.status !== 429) break;
      } catch {
        /* Retry delivery with the same event ID/receipt. */
      }
      if (attempt < 2)
        await new Promise((resolve) =>
          setTimeout(
            resolve,
            (options.retryDelayMs ?? 150) * 2 ** attempt + Math.random() * 50,
          ),
        );
    }
    dropped();
  }
  function drain() {
    if (pending || !queue.length) return;
    pending = (async () => {
      while (queue.length) await send(queue.shift()!);
    })().finally(() => {
      pending = undefined;
      drain();
    });
  }
  function enqueue(path: string, body: unknown) {
    if (closed) return;
    if (queue.length >= 200) {
      dropped();
      return;
    }
    queue.push({ path, body });
    drain();
  }
  const register = () =>
    enqueue('gateway/reader/register', {
      schema_version: 1,
      reader_version: '0.3.0',
      capabilities: ['tool_lifecycle', 'provider_outcomes'],
    });
  async function flush(timeoutMs = 5000) {
    if (!pending) return;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    await Promise.race([
      pending,
      new Promise<void>((resolve) => {
        timeout = setTimeout(resolve, timeoutMs);
      }),
    ]);
    if (timeout) clearTimeout(timeout);
  }
  return {
    event: (event) => enqueue('gateway/reader/events', event),
    outcome: (outcome) => enqueue('gateway/outcomes', outcome),
    start() {
      if (timer || closed) return;
      register();
      timer = setInterval(register, 60_000);
      timer.unref?.();
    },
    flush,
    async close() {
      closed = true;
      if (timer) clearInterval(timer);
      timer = undefined;
      await flush();
      queue.length = 0;
    },
  };
}

export function startObservation(
  telemetry: ReaderTelemetry | undefined,
  actionName: string,
  token?: string,
) {
  const started = performance.now();
  const invocationId = randomUUID();
  const common = {
    schema_version: 1 as const,
    invocation_id: invocationId,
    method: 'tools/call' as const,
    action_name: actionName,
  };
  telemetry?.event({
    ...common,
    event_id: randomUUID(),
    phase: 'started',
    occurred_at: new Date().toISOString(),
    ...(token ? { action_token: token } : {}),
  });
  let finished = false;
  return (
    outcome: NonNullable<ReaderEvent['outcome']>,
    errorCode?: ReaderEvent['error_code'],
  ) => {
    if (finished) return;
    finished = true;
    telemetry?.event({
      ...common,
      event_id: randomUUID(),
      phase: 'completed',
      occurred_at: new Date().toISOString(),
      duration_ms: Math.min(
        86_400_000,
        Math.max(0, Math.round(performance.now() - started)),
      ),
      outcome,
      ...(errorCode ? { error_code: errorCode } : {}),
      ...(token ? { action_token: token } : {}),
    });
  };
}

/** Wrap the actual MCP handler: transport HTTP 200 does not prove tool success. */
export async function observeTool<T>(
  telemetry: ReaderTelemetry | undefined,
  actionName: string,
  token: string | undefined,
  handler: () => Promise<T>,
): Promise<T> {
  const finish = startObservation(telemetry, actionName, token);
  try {
    const result = await handler();
    const failed =
      result !== null &&
      typeof result === 'object' &&
      'isError' in result &&
      result.isError === true;
    finish(failed ? 'FAILED' : 'SUCCEEDED', failed ? 'tool_error' : undefined);
    return result;
  } catch (error) {
    const cancelled = error instanceof Error && error.name === 'AbortError';
    finish(
      cancelled ? 'CANCELLED' : 'FAILED',
      cancelled ? 'cancelled' : 'handler_exception',
    );
    throw error;
  }
}
