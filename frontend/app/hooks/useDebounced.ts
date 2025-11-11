// General-purpose debouncing hook that prevents duplicate function calls within a time window.
// Uses argument-based deduplication to prevent the same call from executing multiple times.

import { useRef, useCallback } from 'react';

interface DebounceEntry {
  key: string;
  timestamp: number;
}

/**
 * Creates a debounced version of a function that prevents duplicate calls within a time window.
 *
 * @param fn - The function to debounce
 * @param delay - Debounce window in milliseconds (default: 1000ms)
 * @param keyExtractor - Optional function to extract a deduplication key from arguments
 * @returns Debounced version of the function
 */
export function useDebounced<T extends (...args: any[]) => any>(
  fn: T,
  delay: number = 1000,
  keyExtractor?: (...args: Parameters<T>) => string
): T {
  const recentCallsRef = useRef<Map<string, DebounceEntry>>(new Map());

  const debouncedFn = useCallback((...args: Parameters<T>): ReturnType<T> | null => {
    const now = Date.now();

    // Extract key for deduplication
    const key = keyExtractor ? keyExtractor(...args) : JSON.stringify(args);

    // Check if we've called this recently
    const recent = recentCallsRef.current.get(key);

    if (recent && now - recent.timestamp < delay) {
      // Suppress duplicate call
      return null;
    }

    // Update or add entry
    recentCallsRef.current.set(key, { key, timestamp: now });

    // Cleanup old entries (older than debounce window)
    const cutoff = now - delay;
    for (const [entryKey, entry] of recentCallsRef.current.entries()) {
      if (entry.timestamp < cutoff) {
        recentCallsRef.current.delete(entryKey);
      }
    }

    // Execute the function
    return fn(...args);
  }, [fn, delay, keyExtractor]) as T;

  return debouncedFn;
}
