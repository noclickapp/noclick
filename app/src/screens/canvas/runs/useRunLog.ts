// The run log's data: a page of runs at a time and the counts by status and by how runs started, read through the
// canvas's run reads (`canvas.runs.reads`, or the reads a host hands in). The first page and the counts are read when a
// workflow opens; a change of filters reads the first page again; scrolling near the end reads the next. Whoever
// renders the canvas keeps the rows themselves (it also adds a run the moment it starts one) and tells this when a run
// starts or ends, so the counts are read again.
import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react';
import type { RunReads } from './reads';
import type { ExecutionCounts, LogsFilters, WorkflowExecutionLog } from './RunLog';

const NO_COUNTS: ExecutionCounts = {
    total: 0,
    byStatus: { running: 0, waiting: 0, success: 0, error: 0 },
    byTrigger: {},
};

const EVERYTHING: LogsFilters = { status: 'all', trigger: 'all', query: '' };

/** How many runs a page holds. */
export const RUN_LOG_PAGE = 50;
/** How long the counts wait after a run starts or ends, so a burst of them is one read. */
const COUNTS_SETTLE_MS = 750;

export interface RunLog {
    counts: ExecutionCounts;
    hasMore: boolean;
    loading: boolean;
    /** Why the last read failed; null once one works. */
    error: string | null;
    /** What reads the page after the last one read; null on the last (set to null to start over). */
    nextCursorRef: RefObject<unknown | null>;
    /** Reads a page (`cursor` null: the first, replacing the rows), answering its rows; undefined when it failed or a
     *  newer read overtook it. */
    fetchPage: (cursor: unknown | null) => Promise<WorkflowExecutionLog[] | undefined>;
    onFiltersChange: (filters: LogsFilters) => void;
    onLoadMore: () => void;
    /** Reads the counts again shortly (a run started or ended). */
    countsChanged: () => void;
}

/** The run log of `workflowId` (nothing is read while it's undefined), its rows kept through `setLogs`. */
export function useRunLog({
    workflowId,
    reads,
    setLogs,
}: {
    workflowId: string | undefined;
    reads: RunReads;
    setLogs: Dispatch<SetStateAction<WorkflowExecutionLog[]>>;
}): RunLog {
    const [counts, setCounts] = useState<ExecutionCounts>(NO_COUNTS);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const nextCursorRef = useRef<unknown | null>(null);
    const filtersRef = useRef<LogsFilters>(EVERYTHING);
    // Each read takes a token and the latest wins: a slow first page never replaces what a later change of filters read.
    const tokenRef = useRef(0);

    const fetchPage = useCallback(
        async (cursor: unknown | null) => {
            if (!workflowId) return;
            const token = ++tokenRef.current;
            setLoading(true);
            try {
                const page = await reads.runs(workflowId, { limit: RUN_LOG_PAGE, filters: filtersRef.current, cursor });
                if (token !== tokenRef.current) return;
                setLogs((prev) => (cursor ? [...prev, ...page.logs] : page.logs));
                nextCursorRef.current = page.next;
                setHasMore(page.next !== null);
                setError(null);
                return page.logs;
            } catch (e) {
                console.error('[run log] A page of runs couldn’t be read:', e);
                if (token === tokenRef.current) setError(e instanceof Error ? e.message : String(e));
            } finally {
                if (token === tokenRef.current) setLoading(false);
            }
        },
        [workflowId, setLogs, reads]
    );

    const fetchCounts = useCallback(async () => {
        if (!workflowId) return;
        try {
            setCounts(await reads.counts(workflowId));
        } catch (e) {
            console.error('[run log] The run counts couldn’t be read:', e);
        }
    }, [workflowId, reads]);

    // The first page and the counts, when a workflow opens.
    useEffect(() => {
        if (!workflowId) return;
        nextCursorRef.current = null;
        filtersRef.current = EVERYTHING;
        fetchPage(null);
        fetchCounts();
    }, [workflowId]); // eslint-disable-line react-hooks/exhaustive-deps

    // A change of filters reads the first page again: the rows are the server's for the new filters, from the top.
    const onFiltersChange = useCallback(
        (filters: LogsFilters) => {
            const prev = filtersRef.current;
            if (prev.status === filters.status && prev.trigger === filters.trigger && prev.query === filters.query) return;
            filtersRef.current = filters;
            nextCursorRef.current = null;
            fetchPage(null);
        },
        [fetchPage]
    );

    const onLoadMore = useCallback(() => {
        if (loading || !nextCursorRef.current) return;
        fetchPage(nextCursorRef.current);
    }, [loading, fetchPage]);

    const settleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const countsChanged = useCallback(() => {
        if (settleRef.current) clearTimeout(settleRef.current);
        settleRef.current = setTimeout(() => {
            fetchCounts();
        }, COUNTS_SETTLE_MS);
    }, [fetchCounts]);

    return { counts, hasMore, loading, error, nextCursorRef, fetchPage, onFiltersChange, onLoadMore, countsChanged };
}
