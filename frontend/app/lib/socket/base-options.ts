// Shared Socket.IO client options, split out of config.ts so the anonymous
// ShareSocket (public /a/{linkId} agent pages) can reuse them WITHOUT
// importing config.ts — which statically pulls supabase-client (and with it
// the whole auth stack) into whatever bundle imports it.

export const BASE_SOCKET_OPTIONS = {
  path: '/socket.io/',
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  timeout: 20000,
  transports: ['websocket', 'polling'],
  withCredentials: true,
};
