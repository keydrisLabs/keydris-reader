import { createKitReader } from '@keydris/kit-reader';
import { keydrisCredentials } from '@keydris/kit-reader/express';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express from 'express';
import { config } from './config.js';
import { createServer } from './server.js';

// One reader for the process: it holds no per-request state, only where to
// redeem and which legacy header to fall back to.
const reader = createKitReader({
  gatewayUrl: config.gatewayUrl,
  tokenHeader: config.tokenHeader,
});

const app = express();
app.use(express.json());

app.use((req, _res, next) => {
  const rpc = (req.body as { method?: string } | undefined)?.method;
  console.log(`${req.method} ${req.path}${rpc ? ` · ${rpc}` : ''}`);
  next();
});

app.get('/healthz', (_req, res) => {
  res.json({ ok: true });
});

app.post('/mcp', keydrisCredentials(reader), async (req, res) => {
  // Stateless: no session id, a fresh server and transport per request. The MCP
  // session would otherwise outlive the access token that authorized it.
  const server = createServer(req.redemption);
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });
  res.on('close', () => {
    void transport.close();
    void server.close();
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch {
    if (!res.headersSent) {
      res.status(500).json({ error: { code: 'internal_error' } });
    }
  }
});

for (const method of ['get', 'delete'] as const) {
  app[method]('/mcp', (_req, res) => {
    res.status(405).json({ error: { code: 'method_not_allowed' } });
  });
}

app.listen(config.port, () => {
  console.log(
    `keydris-github-demo listening on :${config.port}/mcp — redeeming at ${config.gatewayUrl}`,
  );
});
