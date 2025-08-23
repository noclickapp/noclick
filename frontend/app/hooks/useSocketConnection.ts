/**
 * React hook for socket connection status.
 * Provides direct access to socket connection state without needing a context provider.
 */

import { useEffect, useState } from 'react';
import { socketReceiver, type SocketEnvironment } from '~/lib/socket-receiver';

/**
 * Hook to track socket connection status.
 * 
 * @param environment - Which socket environment to track (default: 'API')
 * @returns boolean indicating if the socket is connected
 * 
 * @example
 * function MyComponent() {
 *   const isConnected = useSocketConnection();
 *   const isDataEngineConnected = useSocketConnection('DATA_ENGINE');
 * }
 */
export function useSocketConnection(environment: SocketEnvironment = 'API'): boolean {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    // Check current connection status
    const socket = socketReceiver.getSocket(environment);
    setIsConnected(socket?.connected ?? false);

    // Subscribe to connection changes
    const unsubscribe = socketReceiver.subscribeConnection(environment, setIsConnected);

    return unsubscribe;
  }, [environment]);

  return isConnected;
}