// Persistent preference for which I/O view a user wants by default —
// 'suggested' (the Fields tab) or 'json' (the raw tree). Stored in
// localStorage so it survives reloads, with an in-memory listener set so
// every IODataDisplay on screen snaps in lock-step when one of them is
// toggled. The Table and Loop tabs stay ad-hoc (per-card) and don't
// affect this preference.

import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'noclick:io-view-preference';
// JSON is the default during the staged Fields rollout. Flip
// to 'suggested' once the curated list is trusted enough to be the
// out-of-the-box experience.
const DEFAULT_PREF: IOViewPreference = 'json';

export type IOViewPreference = 'suggested' | 'json';

const isPreference = (v: unknown): v is IOViewPreference =>
    v === 'suggested' || v === 'json';

let current: IOViewPreference = (() => {
    if (typeof window === 'undefined') return DEFAULT_PREF;
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return isPreference(saved) ? saved : DEFAULT_PREF;
})();

const listeners = new Set<() => void>();

const subscribe = (cb: () => void) => {
    listeners.add(cb);
    return () => { listeners.delete(cb); };
};

export const getIOViewPreference = (): IOViewPreference => current;

export const setIOViewPreference = (next: IOViewPreference): void => {
    if (current === next) return;
    current = next;
    if (typeof window !== 'undefined') {
        window.localStorage.setItem(STORAGE_KEY, next);
    }
    listeners.forEach(l => l());
};

/** Subscribe to the global IO view preference. Re-renders when any other
    consumer changes it. */
export function useIOViewPreference(): IOViewPreference {
    return useSyncExternalStore(subscribe, getIOViewPreference, () => DEFAULT_PREF);
}
