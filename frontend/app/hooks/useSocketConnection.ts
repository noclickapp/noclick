/**
 * React hook for socket connection status.
 * Provides direct access to socket connection state without needing a context provider.
 */

import { useEffect, useMemo, useCallback, useSyncExternalStore } from 'react';
import { socketReceiver, type SocketEnvironment, type SocketConnectionState } from '~/lib/socket-receiver';

interface HookConnectionState extends SocketConnectionState {
  isConnected: boolean;
  isConnecting: boolean;
}

const toHookState = (state: SocketConnectionState): HookConnectionState => {
  const status = state?.status ?? 'disconnected';
  return {
    ...state,
    status,
    isConnected: status === 'connected',
    isConnecting: status === 'connecting',
  };
};

/**
 * Hook to track socket connection status.
 * 
 * @param environment - Which socket environment to track (default: 'API')
 * @returns boolean indicating if the socket is connected
 * 
 * @example
 * function MyComponent() {
 *   const { isConnected, status } = useSocketConnection();
 * }
 */
export function useSocketConnection(environment: SocketEnvironment = 'API'): HookConnectionState {
  const subscribe = useCallback((onStoreChange: () => void) => {
    return socketReceiver.subscribeConnection(environment, () => {
      onStoreChange();
    });
  }, [environment]);

  const getSnapshot = useCallback(() => socketReceiver.getConnectionState(environment), [environment]);

  const connectionState = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    socketReceiver.getSocket(environment);
  }, [environment]);

  return useMemo(() => toHookState(connectionState), [connectionState]);
}

export type { HookConnectionState as UseSocketConnectionState };
