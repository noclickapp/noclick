// Persistent key-value state via state-manager nodes.

import { request, subscribe } from './transport.js';

interface StateOptions {
  /** Target a specific state-manager node instead of the auto-detected one. */
  node?: string;
}

/** Read a state value. */
export function get<T = unknown>(key: string, options?: StateOptions): Promise<T | undefined> {
  return request('state.get', { key, ...options });
}

/** Set a state value (overwrites). */
export function set(key: string, value: unknown, options?: StateOptions): Promise<void> {
  return request('state.set', { key, value, ...options });
}

/** Delete a state key. */
export function del(key: string, options?: StateOptions): Promise<void> {
  return request('state.delete', { key, ...options });
}

/**
 * Update a state value with a function (read-modify-write).
 * The updater runs locally in the iframe — not on the server.
 */
export async function update<T = unknown>(
  key: string,
  updater: (current: T | undefined) => T,
  options?: StateOptions
): Promise<void> {
  const current = await get<T>(key, options);
  const next = updater(current);
  await set(key, next, options);
}

/** Subscribe to state changes for a key. Returns unsubscribe function. */
export function onChange<T = unknown>(key: string, handler: (newValue: T) => void): () => void {
  return subscribe('state:changed', (data: unknown) => {
    const d = data as { key: string; value: unknown };
    if (d.key === key) handler(d.value as T);
  });
}

/** List all available state keys across state-manager nodes. */
export function keys(options?: StateOptions): Promise<string[]> {
  return request('state.keys', { ...options });
}
