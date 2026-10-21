import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import type { LazyTypeStore } from '~/lib/lazyTypeStore';

// The server renders every gate closed, so hydration matches a client that hasn't loaded yet.
const SERVER_VERSION = -1;

/**
 * Loads `types` from a per-type store and re-renders as they land; true once all have loaded. A load that fails
 * throws into the nearest error boundary rather than leaving the reader waiting.
 */
export function useLazyTypes<V>(store: LazyTypeStore<V>, types: Iterable<string | null | undefined>): boolean {
    const key = useMemo(
        () => [...new Set([...types].filter((type): type is string => !!type))].sort().join(','),
        [types],
    );
    const version = useSyncExternalStore(store.subscribe, store.version, () => SERVER_VERSION);
    const [error, setError] = useState<unknown>(null);
    useEffect(() => {
        if (key) store.load(key.split(',')).catch(setError);
    }, [store, key]);
    if (error) throw error;
    return version !== SERVER_VERSION && (!key || store.loaded(key.split(',')));
}
