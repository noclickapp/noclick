/**
 * React hook for socket connection status.
 * Provides direct access to socket connection state without needing a context provider.
 */

import { useEffect, useState } from 'react';
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
 *   const dataEngine = useSocketConnection('DATA_ENGINE');
 *   if (dataEngine.isConnecting) {
 *     // show loading UI
 *   }
 * }
 */
export function useSocketConnection(environment: SocketEnvironment = 'API'): HookConnectionState {
  const [connectionState, setConnectionState] = useState<HookConnectionState>(() => {
    const initialState = socketReceiver.getConnectionState(environment);
    return toHookState(initialState);
  });

  useEffect(() => {
    // Check current connection status
    socketReceiver.getSocket(environment);

    // Subscribe to connection changes
    const unsubscribe = socketReceiver.subscribeConnection(environment, (state) => {
      setConnectionState(toHookState(state));
    });

    return unsubscribe;
  }, [environment]);

  return connectionState;
}

export type { HookConnectionState as UseSocketConnectionState };
