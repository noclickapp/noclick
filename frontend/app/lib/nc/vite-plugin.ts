// Vite plugin that bridges CLI/MCP tools to the browser via HMR WebSocket.
// Adds an HTTP middleware at /__nc that relays requests to the browser,
// waits for results via the HMR channel, and writes the dev server port to .nc-port.

import type { Plugin, ViteDevServer } from 'vite';
import fs from 'fs';
import path from 'path';

interface PendingRequest {
  resolve: (result: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
}

export function ncPlugin(): Plugin {
  let server: ViteDevServer;
  const pending = new Map<string, PendingRequest>();
  let idCounter = 0;

  return {
    name: 'nc-bridge',
    apply: 'serve',

    configureServer(_server) {
      server = _server;

      // Listen for results from browser via HMR
      server.ws.on('nc:result', (data: { id: string; result?: unknown; error?: string }) => {
        const req = pending.get(data.id);
        if (!req) return;
        pending.delete(data.id);
        clearTimeout(req.timer);
        req.resolve(data.error ? { ok: false, error: data.error } : { ok: true, result: data.result });
      });

      // HTTP middleware — registered before Vite/Remix internal middleware
      server.middlewares.use('/__nc', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end(JSON.stringify({ error: 'POST only' }));
          return;
        }

        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          let parsed: { file?: string; expr?: string; timeout?: number };
          try {
            parsed = JSON.parse(body);
          } catch {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'Invalid JSON' }));
            return;
          }

          const { file, expr, timeout = 5000 } = parsed;
          if (!file && !expr) {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'Provide file or expr' }));
            return;
          }

          const id = `nc-${++idCounter}-${Date.now().toString(36)}`;

          // Create promise that resolves when browser responds
          const resultPromise = new Promise<unknown>((resolve) => {
            const timer = setTimeout(() => {
              pending.delete(id);
              resolve({ ok: false, error: `Timeout after ${timeout}ms — is a browser tab open?` });
            }, timeout);
            pending.set(id, { resolve, timer });
          });

          // Send to browser via HMR
          server.ws.send('nc:run', { id, file, expr });

          // Wait and respond
          resultPromise.then((result) => {
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(result));
          });
        });
      });

      // Write port file when server starts listening
      server.httpServer?.once('listening', () => {
        const address = server.httpServer?.address();
        if (address && typeof address === 'object') {
          const portFile = path.join(server.config.root, '.nc-port');
          fs.writeFileSync(portFile, String(address.port));
        }
      });
    },
  };
}
