// Per-workflow viewport cache. Reads synchronously so the canvas restores its
// last pan/zoom the moment a workflow remounts (bypasses async state init
// that would otherwise cause a zoom flash). An in-memory Map is the source of
// truth during a session; localStorage is the cold-start fallback.

export interface Viewport {
    x: number;
    y: number;
    zoom: number;
}

const memoryCache = new Map<string, Viewport>();
let writeTimer: ReturnType<typeof setTimeout> | null = null;

const storageKey = (workflowId: string) => `nc-viewport:${workflowId}`;

export function getCachedViewport(workflowId: string): Viewport | null {
    const mem = memoryCache.get(workflowId);
    if (mem) return mem;
    try {
        const stored = localStorage.getItem(storageKey(workflowId));
        if (!stored) return null;
        const parsed = JSON.parse(stored);
        if (parsed && typeof parsed.x === 'number' && typeof parsed.zoom === 'number' && parsed.zoom > 0) {
            memoryCache.set(workflowId, parsed);
            return parsed;
        }
    } catch {
        /* localStorage disabled / JSON malformed — ignore */
    }
    return null;
}

// Debounce localStorage writes so rapid pan/zoom updates don't thrash the main thread.
export function setCachedViewport(workflowId: string, viewport: Viewport): void {
    memoryCache.set(workflowId, viewport);
    if (writeTimer) clearTimeout(writeTimer);
    writeTimer = setTimeout(() => {
        try {
            localStorage.setItem(storageKey(workflowId), JSON.stringify(viewport));
        } catch {
            /* localStorage write failed (quota, private mode) — ignore */
        }
    }, 1000);
}
