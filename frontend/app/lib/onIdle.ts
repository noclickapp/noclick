/** Runs `run` once the browser is idle (bounded by `timeout`); returns a cancel. Older Safari has no
 *  requestIdleCallback: a short breather stands in. */
export function onIdle(run: () => void, timeout = 1500): () => void {
    if (typeof requestIdleCallback === 'function') {
        const id = requestIdleCallback(run, { timeout });
        return () => cancelIdleCallback(id);
    }
    const t = setTimeout(run, 200);
    return () => clearTimeout(t);
}
