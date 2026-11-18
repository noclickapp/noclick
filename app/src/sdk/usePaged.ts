// Cursor pagination over an SDK listPage: the first page is a cached useV1
// read (so it refreshes with focus and invalidateV1); "Load more" appends by
// nextCursor, de-duplicated by id when the first page shifts under it.
import { useCallback, useState } from 'react';
import type { Page } from 'noclick';
import { useV1, type V1Options } from '@/sdk/useV1';

export interface PagedState<T> {
    rows: T[];
    nextCursor: string | null;
    loading: boolean;
    loadingMore: boolean;
    /** Any failure, the first page's or a "Load more"'s (for a caller that shows one panel). */
    error: unknown;
    /** A failed "Load more": DataTable shows it in the footer, where Retry loads more again. */
    loadMoreError: unknown;
    loadMore: () => Promise<void>;
    refresh: () => Promise<void>;
}

export function usePaged<T>(
    key: string | null,
    fetchPage: (cursor: string | null) => Promise<Page<T>>,
    getId: (row: T) => string,
    options: V1Options = {}
): PagedState<T> {
    const first = useV1(key, () => fetchPage(null), options);
    const [more, setMore] = useState<{ key: string | null; rows: T[]; cursor: string | null | undefined; error: unknown }>({
        key,
        rows: [],
        cursor: undefined,
        error: undefined,
    });
    const [loadingMore, setLoadingMore] = useState(false);
    const extra = more.key === key ? more : { key, rows: [] as T[], cursor: undefined, error: undefined };

    const seen = new Set<string>();
    const rows: T[] = [];
    for (const row of [...(first.data?.data ?? []), ...extra.rows]) {
        const id = getId(row);
        if (seen.has(id)) continue;
        seen.add(id);
        rows.push(row);
    }
    const nextCursor = extra.cursor !== undefined ? extra.cursor : (first.data?.nextCursor ?? null);

    const loadMore = useCallback(async () => {
        if (!nextCursor || loadingMore) return;
        setLoadingMore(true);
        try {
            const page = await fetchPage(nextCursor);
            setMore({ key, rows: [...extra.rows, ...page.data], cursor: page.nextCursor, error: undefined });
        } catch (error) {
            setMore({ ...extra, key, error });
        } finally {
            setLoadingMore(false);
        }
    }, [nextCursor, loadingMore, fetchPage, key, extra]);

    const refresh = useCallback(async () => {
        setMore({ key, rows: [], cursor: undefined, error: undefined });
        await first.refresh();
    }, [first, key]);

    return { rows, nextCursor, loading: first.loading, loadingMore, error: first.error ?? extra.error, loadMoreError: extra.error, loadMore, refresh };
}
