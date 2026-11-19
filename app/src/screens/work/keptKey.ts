// Where Work keeps its copy of an account's own perspective in this browser (kept.ts), and forgetting it: a module of
// its own, so signing out of any page forgets it without loading Work.
import { valtioCache } from '@/lib/indexeddb';

/** Where an account's own perspective is kept. */
export const keptKey = (account: string) => `work:${account}:own`;

/** Forgets what this browser kept for `account` (signing out of a browser others use). */
export async function dropKept(account: string): Promise<void> {
    try {
        await valtioCache.delete(keptKey(account));
    } catch {
        // Nothing was kept, or storage refuses: there's nothing to forget.
    }
}
