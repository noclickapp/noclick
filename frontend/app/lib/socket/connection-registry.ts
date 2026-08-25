/**
 * Lightweight store for per-environment connection state. Keeps the latest status and notifies
 * subscribers whenever it changes.
 */

import type { ConnectionHandler, SocketConnectionState } from './types';

export class ConnectionRegistry<Environment extends string> {
  private readonly state = new Map<Environment, SocketConnectionState>();
  private readonly handlers = new Map<Environment, Set<ConnectionHandler>>();

  get(env: Environment): SocketConnectionState {
    return this.state.get(env) ?? { status: 'disconnected' };
  }

  update(env: Environment, updates: Partial<SocketConnectionState>): SocketConnectionState {
    const current = this.get(env);
    const status = updates.status ?? current.status ?? 'disconnected';
    const reconnectAttempt = status === 'connecting'
      ? updates.reconnectAttempt ?? current.reconnectAttempt ?? 0
      : undefined;

    const next: SocketConnectionState = {
      ...current,
      ...updates,
      status,
      reconnectAttempt,
    };

    if (status === 'connected') {
      next.reconnectAttempt = undefined;
      next.lastError = undefined;
      next.lastErrorCode = undefined;
    }

    this.state.set(env, next);
    this.notify(env, next);
    return next;
  }

  subscribe(env: Environment, handler: ConnectionHandler): () => void {
    if (!this.handlers.has(env)) {
      this.handlers.set(env, new Set());
    }

    const envHandlers = this.handlers.get(env)!;
    envHandlers.add(handler);

    // Emit current state immediately
    try {
      handler(this.get(env));
    } catch (error) {
      console.error(`Error in initial connection handler for ${env}:`, error);
    }

    return () => {
      this.handlers.get(env)?.delete(handler);
    };
  }

  removeAll(env?: Environment): void {
    if (env) {
      this.handlers.delete(env);
      this.state.delete(env);
      return;
    }

    this.handlers.clear();
    this.state.clear();
  }

  private notify(env: Environment, state: SocketConnectionState): void {
    const envHandlers = this.handlers.get(env);
    if (!envHandlers) {
      return;
    }

    envHandlers.forEach(handler => {
      try {
        handler(state);
      } catch (error) {
        console.error(`Error in connection handler for ${env}:`, error);
      }
    });
  }
}
