/**
 * React hook for type-safe socket event subscriptions.
 * Uses the centralized socket receiver for consistent event handling.
 */

import { useEffect, useRef } from 'react';
import { onSocketEvent } from '~/lib/socket-receiver';
import type { ServerToClientEvents } from '~/types/socket-events.generated';

type EventHandler<K extends keyof ServerToClientEvents> = 
  ServerToClientEvents[K] extends (...args: infer P) => void ? (...args: P) => void : never;

/**
 * Type-safe hook for subscribing to socket events in React components.
 * Automatically unsubscribes when the component unmounts or dependencies change.
 * 
 * @param event - The event name (autocompleted with valid events)
 * @param handler - Type-safe callback that receives the correct data type
 * @param deps - Optional dependency array (defaults to empty array)
 * 
 * @example
 * // In a React component
 * useSocketEvent('chat:message', (data) => {
 *   // TypeScript knows that data is ChatMessageEvent
 *   console.log(data.message, data.status);
 * });
 * 
 * // With dependencies
 * useSocketEvent('chat:transcription', (data) => {
 *   setTranscription(data.transcription);
 * }, [setTranscription]);
 */
export function useSocketEvent<K extends keyof ServerToClientEvents>(
  event: K,
  handler: EventHandler<K>,
  deps: React.DependencyList = []
): void {
  // Use ref to store the callback to avoid re-subscribing on every render
  const handlerRef = useRef(handler);
  
  // Update the callback ref when it changes
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);
  
  useEffect(() => {
    // Create a stable callback that calls the current ref
    const stableHandler: EventHandler<K> = ((...args) => {
      handlerRef.current(...args);
    }) as EventHandler<K>;
    
    // Subscribe through the centralized receiver
    const unsubscribe = onSocketEvent(event, stableHandler);
    
    // Cleanup: unsubscribe when component unmounts or dependencies change
    return unsubscribe;
  }, [event, ...deps]);
}