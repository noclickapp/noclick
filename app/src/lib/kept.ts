// What this browser keeps of an account between visits (Work's spaces and channels, the reads screens keep, the
// Automations list), so a screen opens on what it showed last and reads it again behind it. A copy is an account's own
// (its key names the account, and a page reads only the copy of the account it acts as), shape-versioned (a copy of
// another version is dropped), and signing out forgets every copy in the browser. Storage that's missing, slow or
// throwing leaves a screen as it is without one.
import { valtioCache } from '@/lib/indexeddb';

/** How long a screen waits on this browser's storage before it opens without a copy. */
export const KEPT_WAIT_MS = 250;

interface Copy<T> {
    version: number;
    value: T;
}

const keyOf = (account: string, what: string) => `kept:${account}:${what}`;

/** What was kept as `what` for `account` at `version`; null when there's none (or storage didn't answer in time). */
export async function readKept<T>(account: string, what: string, version: number): Promise<T | null> {
    let copy: Copy<T> | null = null;
    try {
        copy = await Promise.race([valtioCache.get<Copy<T>>(keyOf(account, what)), new Promise<null>((resolve) => setTimeout(() => resolve(null), KEPT_WAIT_MS))]);
    } catch {
        return null;
    }
    if (!copy) return null;
    if (copy.version === version) return copy.value;
    void valtioCache.delete(keyOf(account, what)).catch(() => undefined);
    return null;
}

/** Keeps `value` (plain data: IndexedDB clones it) as `what` for `account`. */
export function keepFor<T>(account: string, what: string, version: number, value: T): void {
    void valtioCache.set<Copy<T>>(keyOf(account, what), { version, value }).catch(() => undefined);
}

/** Calls `keep` whenever the page hides or goes, and once more when the returned function stops it (its screen
 *  leaving). */
export function keepWhenLeaving(keep: () => void): () => void {
    const hidden = () => document.visibilityState === 'hidden' && keep();
    window.addEventListener('pagehide', keep);
    document.addEventListener('visibilitychange', hidden);
    return () => {
        window.removeEventListener('pagehide', keep);
        document.removeEventListener('visibilitychange', hidden);
        keep();
    };
}

/** Forgets everything this browser keeps for any account (signing out of a browser others may use): every copy above,
 *  and whatever else the app keeps in this browser's storage (a canvas, a balance), which belongs to whoever was signed
 *  in. */
export async function forgetKept(): Promise<void> {
    try {
        await valtioCache.clear();
    } catch {
        // Storage refuses: there's nothing it kept to forget.
    }
}
