// Returns true once the browser has gone idle after hydration (requestIdleCallback,
// bounded by `timeout`). Used to defer mounting heavy lazy chunks (e.g. the canvas
// preview's ReactFlow + node registry) so their download and parsing do not
// compete with the initial render.
import { useEffect, useState } from 'react';

export function useIdleReady(timeout = 1500): boolean {
    const [ready, setReady] = useState(false);
    useEffect(() => {
        if (typeof requestIdleCallback === 'function') {
            const id = requestIdleCallback(() => setReady(true), { timeout });
            return () => cancelIdleCallback(id);
        }
        // Older Safari: no rIC — a short post-hydration breather.
        const t = setTimeout(() => setReady(true), 200);
        return () => clearTimeout(t);
    }, [timeout]);
    return ready;
}
