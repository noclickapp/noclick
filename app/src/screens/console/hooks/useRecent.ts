// The palette's Recent group: the last objects this viewer opened. A per-viewer
// convenience, so browser storage (it may be unavailable; the list is then empty).
import { useCallback, useEffect, useState } from 'react';

export interface RecentObject {
    type: string;
    id: string;
    label: string;
    /** Console path (without the base) and params to reopen it. */
    path: string;
    params?: Record<string, string>;
}

const STORAGE_KEY = 'nc-developers-recent';
const MAX = 8;
const EVENT = 'noclick:developers-recent';

function read(): RecentObject[] {
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

/** Pages call this when a drawer or detail page opens an object. */
export function recordRecent(item: RecentObject): void {
    const next = [item, ...read().filter((r) => !(r.type === item.type && r.id === item.id))].slice(0, MAX);
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
        return;
    }
    window.dispatchEvent(new Event(EVENT));
}

export function useRecent(): RecentObject[] {
    const [items, setItems] = useState<RecentObject[]>([]);
    const sync = useCallback(() => setItems(read()), []);
    useEffect(() => {
        sync();
        window.addEventListener(EVENT, sync);
        return () => window.removeEventListener(EVENT, sync);
    }, [sync]);
    return items;
}
