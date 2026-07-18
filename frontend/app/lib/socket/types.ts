/**
 * Shared type definitions for the frontend socket layer, keeping imports tidy across helpers.
 */

import type { ManagerOptions, SocketOptions } from 'socket.io-client';
import type { ServerToClientEvents } from '~/types/socket-events.generated';

export interface SocketConnectionState {
  status: 'disconnected' | 'connecting' | 'connected';
  reconnectAttempt?: number;
  lastConnectedAt?: number;
  lastDisconnectedAt?: number;
  lastDisconnectReason?: string;
  lastError?: string;
  /** Machine code from the backend's ConnectionRefusedError payload
   *  (token_expired | token_invalid | missing_auth | auth_failed | …).
   *  Auth handling keys on this, never on message text. */
  lastErrorCode?: string;
}

export type ConnectionHandler = (state: SocketConnectionState) => void;

export interface SocketEnvironmentConfig {
  url: string;
  events: (keyof ServerToClientEvents)[];
  options?: Partial<ManagerOptions & SocketOptions>;
  lazy?: boolean;
}

export type SocketConfigMap<Environment extends string> = Record<Environment, SocketEnvironmentConfig>;

export type SocketAuthPayload = Record<string, unknown> | string | undefined;

