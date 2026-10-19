// A value read for a key: only the latest key's answer lands, and it's read
// again when the key changes or on reload. For reads one view owns (a repo's
// folder, a file), not state shared across the app.
import { useCallback, useEffect, useRef, useState } from 'react';

export interface Loaded<T> {
    data: T | undefined;
    error: unknown;
    /** True while nothing has answered for this key yet. */
    loading: boolean;
    reload: () => void;
}

export function useLoaded<T>(key: string | null, load: () => Promise<T>): Loaded<T> {
    const [state, setState] = useState<{ key: string | null; data?: T; error?: unknown }>({ key: null });
    const [round, setRound] = useState(0);
    const loadRef = useRef(load);
    loadRef.current = load;

    useEffect(() => {
        if (key === null) return;
        let live = true;
        setState((s) => (s.key === key ? { key, data: s.data } : { key }));
        loadRef.current().then(
            (data) => live && setState({ key, data }),
            (error: unknown) => live && setState({ key, error: error ?? new Error('Could not load it.') })
        );
        return () => {
            live = false;
        };
    }, [key, round]);

    const reload = useCallback(() => setRound((n) => n + 1), []);
    const current = state.key === key ? state : { key, data: undefined, error: undefined };
    return { data: current.data, error: current.error, loading: key !== null && current.data === undefined && current.error === undefined, reload };
}
