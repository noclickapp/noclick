// Vite plugin that bridges CLI/MCP tools to the browser via HMR WebSocket.
// Adds an HTTP middleware at /__nc that relays requests to the browser,
// waits for results via the HMR channel, and writes the dev server port to .nc-port.
// Also provides /__nc/channel SSE endpoint for streaming frontend messages to MCP channel servers.

import type { Plugin, ViteDevServer } from 'vite';
import type { ServerResponse } from 'http';
import type { ChannelMessage } from './channel';
import fs from 'fs';
import path from 'path';

interface PendingRequest {
  resolve: (result: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
}

/** Dedup key: level + first 200 chars of message */
function dedupKey(msg: ChannelMessage): string {
  return `${msg.level}:${msg.message.slice(0, 200)}`;
}

const DEDUP_WINDOW_MS = 5_000;
const MAX_BUFFER = 500;

export function ncPlugin(): Plugin {
  let server: ViteDevServer;
  const pending = new Map<string, PendingRequest>();
  let idCounter = 0;

  // ── Channel state ──────────────────────────────────────────────────────
  const channelBuffer: ChannelMessage[] = [];
  const sseClients = new Set<ServerResponse>();
  /** Tracks last emit time per dedup key to suppress duplicates */
  const recentKeys = new Map<string, number>();

  function pushChannelMessage(msg: ChannelMessage) {
    // Dedup: skip if identical message was pushed within the window
    const key = dedupKey(msg);
    const now = Date.now();
    const lastSeen = recentKeys.get(key);
    if (lastSeen && now - lastSeen < DEDUP_WINDOW_MS) return;
    recentKeys.set(key, now);

    // Prune stale dedup keys periodically
    if (recentKeys.size > 200) {
      for (const [k, t] of recentKeys) {
        if (now - t > DEDUP_WINDOW_MS) recentKeys.delete(k);
      }
    }

    channelBuffer.push(msg);
    if (channelBuffer.length > MAX_BUFFER) channelBuffer.splice(0, channelBuffer.length - MAX_BUFFER);

    // Push to all SSE subscribers
    const data = JSON.stringify(msg);
    for (const res of sseClients) {
      try {
        res.write(`data: ${data}\n\n`);
      } catch {
        sseClients.delete(res);
      }
    }
  }

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

      // Listen for channel messages from browser via HMR
      server.ws.on('nc:channel', (data: ChannelMessage) => {
        pushChannelMessage(data);
      });

      // ── SSE endpoint for channel subscribers ───────────────────────────
      server.middlewares.use('/__nc/channel', (req, res) => {
        if (req.method !== 'GET') {
          res.statusCode = 405;
          res.end('GET only');
          return;
        }

        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        });
        res.write(':ok\n\n');

        sseClients.add(res);
        req.on('close', () => sseClients.delete(res));

        // Send keepalive comment every 30s so subscribers detect dead connections
        const keepalive = setInterval(() => {
          try { res.write(':ping\n\n'); } catch { clearInterval(keepalive); sseClients.delete(res); }
        }, 30_000);
        req.on('close', () => clearInterval(keepalive));
      });

      // ── Existing nc tool relay endpoint ────────────────────────────────
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
