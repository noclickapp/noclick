/**
 * Socket configuration factory. Builds per-environment Socket.IO options and the event routing
 * metadata the receiver needs to operate.
 */

import type { SocketEnvironment } from '~/types/socket-events.generated';
import { EventRouting } from '~/types/socket-events.generated';
import { getExistingBrowserClient } from '~/lib/supabase-client';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { BASE_SOCKET_OPTIONS } from './base-options';
import type { SocketConfigMap } from './types';

export const DEFAULT_EVENT_BUFFER_TTL_MS = 1000; // milliseconds

// Backwards-compatible alias while the rest of the codebase updates or overrides this value.
export const EVENT_BUFFER_TTL_MS = DEFAULT_EVENT_BUFFER_TTL_MS;

// Socket message chunking threshold (1.5 MiB - Some transports have a 2 MiB limit per message)
export const SOCKET_CHUNK_SIZE = 1 * 1024 * 1024;

export function createSocketConfig(autoConnectApi: boolean): SocketConfigMap<SocketEnvironment> {
  return {
    API: {
      // One resolver for every endpoint: on a single-origin install an unset
      // VITE_API_URL means the page's own origin, not "unconfigured".
      url: apiBaseUrl(),
      events: [
        '__chunk__',  // Internal chunking event for large messages
        'chat:message',
        'chat:transcription',
        // Live progress of a staged agent run. Bound here because the socket
        // only dispatches events on this list — an event the backend emits but
        // that is missing here arrives and is silently discarded.
        'rehearsal:progress',
        'conversation:resume',
        'conversations:list',
        'agent:state',
        'credits:exhausted',
        'error',
        'yjs:sync',
        'cache_valtio:state',
        'response',
        'server:data',
        'usage:event',
        'usage:data',
        'workflow:node:state',
        'workflow:node:output',
        'workflow:started',
        'workflow:complete',
        // Workflow MCP events
        'mcp:builder_event',
        'workflow:mcp:request',  // Frontend-required operations (get_selected, open_workflow)
        'mcp:workflow:delete_workflow:response',
        'mcp:workflow:update_workflow_metadata:response',
        'mcp:workflow:create_workflow:response',
        'mcp:workflow:update_interface:response',
        'mcp:builder_event',
        // Approval feed events
        'approval:request:created',
        'approval:request:resolved',
        // Activity log events
        'activity:log:created',
        // Setup flow events (interactive guided onboarding)
        // AI workflow naming (fires once after the first edit on a fresh empty workflow)
        'workflow:name_generated',
      ],
      options: {
        ...BASE_SOCKET_OPTIONS,
        autoConnect: autoConnectApi,
        // Auth callback runs on every connect AND every reconnect attempt
        // (socket.io-client v4 invokes `socket.auth` afresh each handshake;
        // see node_modules/socket.io-client/build/cjs/socket.js:424-433 where
        // _sendConnectPacket is only called from inside the cb invocation,
        // so an async callback correctly defers the handshake).
        //
        // We await `supabase.auth.getSession()` first — the Supabase docs
        // describe it as "Returns the session, refreshing it if necessary",
        // which gives us a free proactive refresh whenever the token is near
        // expiry. This is the documented Supabase pattern (the same one our
        // server-side `requireAuth` uses) and is what closes the gap left by
        // autoRefreshToken pausing while the tab is backgrounded.
        //
        // The payload is the Supabase ACCESS TOKEN (JWT) — never cookies
        // (docs/auth-refactor-spec.md). The backend verifies it and takes
        // identity from the verified sub claim. If the Supabase client hasn't
        // initialized yet (first connect can race useSocketTokenRefresh's
        // mount), we send no token: the backend rejects with missing_auth and
        // the infinite-retry reconnect picks the token up moments later.
        auth: async (cb: (data: object) => void) => {
          const authData: Record<string, unknown> = {};
          try {
            const client = getExistingBrowserClient();
            if (client) {
              const { data } = await client.auth.getSession();
              if (data.session?.access_token) {
                authData.token = data.session.access_token;
              }
            }
          } catch { /* swallow — never let auth refresh failures block the handshake; the backend will reject and we'll reconnect */ }
          cb(authData);
        },
      },
    },
  } satisfies SocketConfigMap<SocketEnvironment>;
}

export { EventRouting };
