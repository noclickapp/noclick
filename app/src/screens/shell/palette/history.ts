// What this browser ran from the command palette, by entry id: how often and when last, so the places a person goes
// to most float up and the latest are offered before anything is typed. A per-viewer convenience: empty when storage
// is unavailable.
const KEY = 'nc-palette-uses';
const KEPT = 60;
const DAY_MS = 86_400_000;

export interface Use {
    count: number;
    at: number;
}

export function readUses(): Record<string, Use> {
    try {
        const parsed: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? '{}');
        return parsed && typeof parsed === 'object' ? (parsed as Record<string, Use>) : {};
    } catch {
        return {};
    }
}

/** Counts a use of `id` now, keeping the most recent few dozen. */
export function recordUse(id: string, now = Date.now()): void {
    const uses = readUses();
    uses[id] = { count: (uses[id]?.count ?? 0) + 1, at: now };
    const kept = Object.entries(uses)
        .sort(([, a], [, b]) => b.at - a.at)
        .slice(0, KEPT);
    try {
        window.localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(kept)));
    } catch {
        // Not remembered this time.
    }
}

/** How strongly a use counts now: often, and lately. */
export function frecency(use: Use | undefined, now = Date.now()): number {
    return use ? use.count / (1 + Math.max(0, now - use.at) / DAY_MS) : 0;
}
