/**
 * Recovery for failed dynamic imports. Every deploy rotates hashed chunk
 * filenames and the prod domain 404s the previous deploy's assets, so a client
 * holding pre-deploy HTML (suspended mobile tab, cached page, long-lived tab)
 * crashes on its next lazy import. One guarded reload picks up fresh HTML with
 * current hashes; the guard keeps a deterministic failure (ad blocker, dead
 * network) from looping into a white-flash reload storm.
 */

const RELOAD_GUARD_KEY = 'nc_boundary_reload_at';
const RELOAD_GUARD_WINDOW_MS = 30_000;

// Each browser words a failed fetch/dynamic import differently — a missing
// wording means that browser shows the error page while the rest self-heal.
const TRANSIENT_CHUNK_ERROR_PATTERNS = [
    'Failed to fetch', // Chrome: fetch + dynamic import
    'NetworkError', // Firefox: fetch
    'Load failed', // Safari: fetch
    'Importing a module script failed', // Safari: dynamic import
    'error loading dynamically imported module', // Firefox: dynamic import
    'Unable to preload CSS', // Vite: CSS dep of a lazy chunk
];

export function isTransientChunkError(message: string): boolean {
    return TRANSIENT_CHUNK_ERROR_PATTERNS.some((p) => message.includes(p));
}

/**
 * Reload at most once per 30s window. The guard is sessionStorage-scoped and
 * shared by the ErrorBoundary and the vite:preloadError listener so the two
 * recovery paths can't ping-pong. Returns true when a reload was initiated.
 */
export function tryGuardedReload(): boolean {
    if (typeof window === 'undefined') return false;
    const last = Number(window.sessionStorage.getItem(RELOAD_GUARD_KEY) || 0);
    if (Date.now() - last <= RELOAD_GUARD_WINDOW_MS) return false;
    window.sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()));
    window.location.reload();
    return true;
}
