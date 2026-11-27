// Live operation lists: each operation's frame (made, started, a stage, a line it printed, its end) has the list ask
// for the rows changed since the newest update it shows, and merge them in: a shown row updates in place, wherever it
// was loaded, and a new one that matches the page's filters goes on top. The ask ignores the page's status filter, or
// a row that finishes under `status:live` would never come back. A list showing nothing reads its first page again.
import { useRef, useState } from 'react';
import { LIVE_OPERATION_STATUSES } from '@/screens/console/lib/status';
import { useReadOnFrames } from './liveReads';

/** A list's status filter as the SDK options carry it (`live` = non-terminal). */
export interface StatusFilter {
    status?: unknown;
    statusNot?: unknown;
}

function statusList(value: unknown): string[] | null {
    if (Array.isArray(value)) return value.map(String);
    return typeof value === 'string' ? [value] : null;
}

function inList(status: string, list: readonly string[]): boolean {
    return list.includes(status) || (list.includes('live') && LIVE_OPERATION_STATUSES.has(status));
}

export function matchesStatus(status: string, filter: StatusFilter): boolean {
    const want = statusList(filter.status);
    const not = statusList(filter.statusNot);
    return (!want || inList(status, want)) && (!not || !inList(status, not));
}

export interface LiveRow {
    id: string;
    status: string;
    createdAt: Date | null;
    updatedAt: Date | null;
}

type Mergeable = { id: string; createdAt: Date | null; updatedAt?: Date | null };

function newer<T extends Mergeable>(a: T, b: T): T {
    return (b.updatedAt?.getTime() ?? 0) >= (a.updatedAt?.getTime() ?? 0) ? b : a;
}

/** Changed rows replace their older selves in place; unseen rows go on top, newest first. */
export function mergeById<T extends Mergeable>(rows: readonly T[], changes: readonly T[]): T[] {
    const byId = new Map(changes.map((c) => [c.id, c]));
    const merged = rows.map((r) => {
        const change = byId.get(r.id);
        return change ? newer(r, change) : r;
    });
    const known = new Set(rows.map((r) => r.id));
    const fresh = changes
        .filter((c) => !known.has(c.id))
        .sort((a, b) => (b.createdAt?.getTime() ?? 0) - (a.createdAt?.getTime() ?? 0));
    return [...fresh, ...merged];
}

function newestUpdate(rows: readonly LiveRow[]): Date | null {
    let max: number | null = null;
    for (const r of rows) {
        const t = r.updatedAt?.getTime();
        if (t != null && (max === null || t > max)) max = t;
    }
    return max === null ? null : new Date(max);
}

export interface LiveOperationsOptions<T extends LiveRow> {
    rows: readonly T[];
    /** Changes when the page's filters change; rows asked for under other filters are dropped. */
    resetKey: string;
    /** Rows matching the page's filters EXCEPT status, with `updatedAfter` set. */
    changedSince: (updatedAfter: Date) => Promise<T[]>;
    /** With no row shown to ask after: the list's first page read again. */
    reread: () => Promise<void>;
    /** The page's status filter: a row first seen by the ask joins only if it matches; shown rows always update. */
    statusFilter?: StatusFilter;
    enabled?: boolean;
}

/** The list's rows with each change merged in, and whether any of them still runs. */
export function useLiveOperations<T extends LiveRow>({
    rows,
    resetKey,
    changedSince,
    reread,
    statusFilter = {},
    enabled = true,
}: LiveOperationsOptions<T>): { rows: T[]; running: boolean } {
    const [changes, setChanges] = useState<{ key: string; rows: T[] }>({ key: resetKey, rows: [] });
    const merged = mergeById(rows, changes.key === resetKey ? changes.rows : []);
    const latest = useRef({ merged, changedSince, reread, resetKey, statusFilter });
    latest.current = { merged, changedSince, reread, resetKey, statusFilter };

    useReadOnFrames(
        'platform:resource',
        (frame) => frame.kind === 'operation',
        async () => {
            const { merged: current, changedSince: ask, reread: readAgain, resetKey: key, statusFilter: filter } = latest.current;
            const since = newestUpdate(current);
            if (!since) return readAgain();
            const got = await ask(since);
            const shown = new Set(current.map((r) => r.id));
            const admitted = got.filter((r) => shown.has(r.id) || matchesStatus(r.status, filter));
            if (admitted.length) setChanges((prev) => ({ key, rows: mergeById(prev.key === key ? prev.rows : [], admitted) }));
        },
        enabled
    );

    return { rows: merged, running: merged.some((r) => LIVE_OPERATION_STATUSES.has(r.status)) };
}
