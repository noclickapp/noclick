// URL-bound state: every tab, filter and open drawer lives in the URL.
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { canonicalQuery, parseQuery, setToken as setQueryToken, type ParsedQuery, type QuerySchema } from '@/screens/console/lib/query';
import { parseUserParam, userParamValue, type UserFilterValue } from '@/screens/console/lib/userFilter';

/**
 * One search param as state; setting null (or '', unless `keepEmpty`) removes it.
 * Replaces history by default (filters, tabs).
 */
export function useSearchParam(
    name: string,
    { keepEmpty = false }: { keepEmpty?: boolean } = {}
): [string | null, (value: string | null, options?: { push?: boolean }) => void] {
    const [params, setParams] = useSearchParams();
    const value = params.get(name);
    const set = useCallback(
        (next: string | null, options: { push?: boolean } = {}) => {
            setParams(
                (prev) => {
                    const out = new URLSearchParams(prev);
                    if (next == null || (next === '' && !keepEmpty)) out.delete(name);
                    else out.set(name, next);
                    return out;
                },
                { replace: !options.push, preventScrollReset: true }
            );
        },
        [name, keepEmpty, setParams]
    );
    return [value, set];
}

export interface ConsoleQuery {
    q: string;
    parsed: ParsedQuery;
    setQ: (q: string) => void;
    /** Facets, shortcuts and pills write their token through this. */
    setToken: (key: string, values: readonly string[] | null, negated?: boolean) => void;
}

/**
 * The page's `?q=`, parsed against its schema and written in canonical form.
 * `defaultQ` applies only while the param is absent: an empty `q=` is a cleared query.
 */
export function useConsoleQuery(schema: QuerySchema, defaultQ = ''): ConsoleQuery {
    const [raw, setRaw] = useSearchParam('q', { keepEmpty: true });
    const q = raw ?? defaultQ;
    const parsed = useMemo(() => parseQuery(q, schema), [q, schema]);
    const setQ = useCallback(
        (next: string) => {
            const canonical = canonicalQuery(next, schema);
            setRaw(canonical === canonicalQuery(defaultQ, schema) ? null : canonical);
        },
        [setRaw, defaultQ, schema]
    );
    const setToken = useCallback(
        (key: string, values: readonly string[] | null, negated = false) => setQ(setQueryToken(q, key, values, negated)),
        [q, setQ]
    );
    return { q, parsed, setQ, setToken };
}

/** `?user=` on pages without a query bar. */
export function useUserParam(): [UserFilterValue, (filter: UserFilterValue) => void] {
    const [raw, setRaw] = useSearchParam('user');
    const filter = parseUserParam(raw);
    const set = useCallback((next: UserFilterValue) => setRaw(userParamValue(next)), [setRaw]);
    return [filter, set];
}
