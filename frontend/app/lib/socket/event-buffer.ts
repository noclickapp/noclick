/**
 * Tiny TTL buffer for socket events. When listeners register late, we can replay the most recent
 * payloads so UI components avoid race conditions.
 */

import type { ServerToClientEvents } from '~/types/socket-events.generated';

export class EventBuffer {
  private readonly buffer = new Map<keyof ServerToClientEvents, Array<{ timestamp: number; args: unknown[] }>>();

  constructor(private readonly ttlMs: number) {}

  compact<E extends keyof ServerToClientEvents>(event: E): void {
    this.trim(event);
  }

  store<E extends keyof ServerToClientEvents>(event: E, args: Parameters<ServerToClientEvents[E]>): void {
    if (!this.buffer.has(event)) {
      this.buffer.set(event, []);
    }

    const items = this.buffer.get(event)!;
    items.push({ timestamp: Date.now(), args });
    this.trim(event);
  }

  replay<E extends keyof ServerToClientEvents>(
    event: E,
    handler: (...args: Parameters<ServerToClientEvents[E]>) => void
  ): void {
    const items = this.buffer.get(event);
    if (!items?.length) {
      return;
    }

    this.trim(event);
    const events = this.buffer.get(event);
    events?.forEach(item => {
      try {
        handler(...(item.args as Parameters<ServerToClientEvents[E]>));
      } catch (error) {
        console.error(`Error replaying buffered event '${event}':`, error);
      }
    });
  }

  clear<E extends keyof ServerToClientEvents>(event?: E): void {
    if (event) {
      this.buffer.delete(event);
    } else {
      this.buffer.clear();
    }
  }

  private trim(event: keyof ServerToClientEvents): void {
    const items = this.buffer.get(event);
    if (!items) return;

    const cutoff = Date.now() - this.ttlMs;
    const next = items.filter(item => item.timestamp > cutoff);

    if (next.length === 0) {
      this.buffer.delete(event);
    } else {
      this.buffer.set(event, next);
    }
  }
}

