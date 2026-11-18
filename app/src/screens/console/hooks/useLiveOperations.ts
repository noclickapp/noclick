// Live refresh for operation lists: while any shown row is non-terminal, poll
// every 5s for rows changed since the newest update seen and merge them in.
// The poll ignores the page's status filter, or a row that finishes under
// `status:live` would never come back and would poll forever.
import { useEffect, useRef, useState } from 'react';
import { LIVE_OPERATION_STATUSES } from '@/screens/console/lib/status';

/** A list's status filter as the SDK options carry it (`live` = non-terminal). */
export interface StatusFilter {
    status?: unknown;
    statusNot?: unknown;
}

/** The page's list options without its status filter: what a live poll sends. */
export function withoutStatus<O extends StatusFilter>(options: O): Omit<O, 'status' | 'statusNot'> {
    const rest: Partial<O> = { ...options };
    delete rest.status;
    delete rest.statusNot;
    return rest as Omit<O, 'status' | 'statusNot'>;
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
    /** Changes when the page's filters change; polled rows from other filters are dropped. */
    resetKey: string;
    /** Rows matching the page's filters EXCEPT status (`withoutStatus(options)`), with `updatedAfter` set. */
    poll: (updatedAfter: Date) => Promise<T[]>;
    /** The page's status filter: a row first seen by the poll joins only if it matches; shown rows always update. */
    statusFilter?: StatusFilter;
    enabled?: boolean;
    intervalMs?: number;
}

export function useLiveOperations<T extends LiveRow>({
    rows,
    resetKey,
    poll,
    statusFilter = {},
    enabled = true,
    intervalMs = 5000,
}: LiveOperationsOptions<T>): { rows: T[]; polling: boolean } {
    const [changes, setChanges] = useState<{ key: string; rows: T[] }>({ key: resetKey, rows: [] });
    const merged = mergeById(rows, changes.key === resetKey ? changes.rows : []);
    const polling = enabled && merged.some((r) => LIVE_OPERATION_STATUSES.has(r.status));
    const latest = useRef({ merged, poll, resetKey, statusFilter });
    latest.current = { merged, poll, resetKey, statusFilter };

    useEffect(() => {
        if (!polling) return;
        const timer = window.setInterval(async () => {
            if (document.hidden) return;
            const { merged: current, poll: fetchChanges, resetKey: key, statusFilter: filter } = latest.current;
            const since = newestUpdate(current);
            if (!since) return;
            let got: T[];
            try {
                got = await fetchChanges(since);
            } catch (err) {
                // One missed tick; the next one asks again from the same point.
                console.warn('Live operations poll failed', err);
                return;
            }
            const shown = new Set(current.map((r) => r.id));
            const admitted = got.filter((r) => shown.has(r.id) || matchesStatus(r.status, filter));
            if (!admitted.length) return;
            setChanges((prev) => ({ key, rows: mergeById(prev.key === key ? prev.rows : [], admitted) }));
        }, intervalMs);
        return () => window.clearInterval(timer);
    }, [polling, intervalMs]);

    return { rows: merged, polling };
}
