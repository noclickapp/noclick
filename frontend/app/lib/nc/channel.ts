// General-purpose channel for pushing messages from the frontend to Claude Code.
// Any frontend code can import { channel } from '~/lib/nc/channel' and call
// channel.error/warn/info/send to push structured messages through the HMR bridge.
// No-ops in production — the HMR transport only exists in dev mode.
// Rate-limited to 10 messages/min to prevent infinite loops from trashing context.

export interface ChannelMessage {
  level: 'error' | 'warn' | 'info';
  message: string;
  /** Optional structured metadata (component name, nodeId, file, etc.) */
  meta?: Record<string, string>;
  ts: string;
}

const MAX_MESSAGE_LENGTH = 1500;
const RATE_LIMIT_MAX = 10;
const RATE_LIMIT_WINDOW_MS = 60_000;

const rateBuckets: number[] = [];
let rateLimitNotified = false;

function isRateLimited(): boolean {
  const now = Date.now();
  while (rateBuckets.length && now - rateBuckets[0] > RATE_LIMIT_WINDOW_MS) {
    rateBuckets.shift();
  }
  return rateBuckets.length >= RATE_LIMIT_MAX;
}

function clip(message: string): string {
  if (message.length <= MAX_MESSAGE_LENGTH) return message;
  return message.slice(0, MAX_MESSAGE_LENGTH) + `\n... (clipped, ${message.length} chars total)`;
}

function emit(level: ChannelMessage['level'], message: string, meta?: Record<string, string>) {
  if (typeof window === 'undefined') return;
  const hot = (import.meta as any).hot;
  if (!hot) return;

  if (isRateLimited()) {
    // Send one rate-limit warning, then drop silently
    if (!rateLimitNotified) {
      rateLimitNotified = true;
      hot.send('nc:channel', {
        level: 'warn',
        message: 'Frontend channel rate limit reached (10/min). Suppressing further messages. This usually means an error is firing in a loop.',
        meta: { source: 'rate-limit' },
        ts: new Date().toISOString(),
      } satisfies ChannelMessage);
      // Reset the flag after the window passes
      setTimeout(() => { rateLimitNotified = false; }, RATE_LIMIT_WINDOW_MS);
    }
    return;
  }

  rateBuckets.push(Date.now());
  hot.send('nc:channel', {
    level,
    message: clip(message),
    meta,
    ts: new Date().toISOString(),
  } satisfies ChannelMessage);
}

export const channel = {
  /** Push an error to the Claude Code channel */
  error(message: string, meta?: Record<string, string>) {
    emit('error', message, meta);
  },
  /** Push a warning to the Claude Code channel */
  warn(message: string, meta?: Record<string, string>) {
    emit('warn', message, meta);
  },
  /** Push an info message to the Claude Code channel */
  info(message: string, meta?: Record<string, string>) {
    emit('info', message, meta);
  },
  /** Push a message with an explicit level */
  send(level: ChannelMessage['level'], message: string, meta?: Record<string, string>) {
    emit(level, message, meta);
  },
};
