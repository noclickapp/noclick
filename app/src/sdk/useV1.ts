// The read cache: a hook for /v1 reads that serves the cached value at once, then revalidates on mount, on focus, on
// an interval (paused while the tab is hidden) and on invalidateV1() after a write. The cache is per client, so two
// clients (the app's and a fixture lab's) never mix.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { NoClick } from 'noclick';
import { useProvidedClient } from '@/sdk/client';

export interface V1State<T> {
    data: T | undefined;
    error: unknown;
    /** True only while nothing (not even a stale value) can be shown. */
    loading: boolean;
    refresh: () => Promise<void>;
    /** Replace the value locally (an optimistic or returned write). */
    mutate: (data: T) => void;
}

export interface V1Options {
    pollMs?: number;
    enabled?: boolean;
    /** The client to read with; the one a `ClientProvider` above gives by default. */
    client?: NoClick;
}

interface Entry {
    data: unknown;
    at: number;
}

const FOCUS_DEDUPE_MS = 1000;
const caches = new WeakMap<object, Map<string, Entry>>();
const revalidators = new Map<string, Set<() => void>>();
/** A cache's reads: the one under way for each key, which a view asking meanwhile shares, and the newest begun (or set
 *  by `mutate`), the only one whose result is kept: a read begun before a write or a local change never lands over what
 *  came after it, in the cache or in a view. */
interface Reads {
    under: Map<string, Promise<unknown>>;
    newest: Map<string, Promise<unknown>>;
}
const readsByCache = new WeakMap<object, Reads>();
const allReads = new Set<Reads>();
// Made on first read: Workers refuse an AbortController made at module scope.
let never: AbortSignal | null = null;
const neverAborted = () => (never ??= new AbortController().signal);

function cacheFor(scope: object): Map<string, Entry> {
    let cache = caches.get(scope);
    if (!cache) caches.set(scope, (cache = new Map()));
    return cache;
}

function readsOf(cache: Map<string, Entry>): Reads {
    let reads = readsByCache.get(cache);
    if (!reads) {
        readsByCache.set(cache, (reads = { under: new Map(), newest: new Map() }));
        allReads.add(reads);
    }
    return reads;
}

/** Begins a read of `key`, the newest from now: its result goes into the cache unless a newer one began meanwhile. */
function begin<T>(cache: Map<string, Entry>, reads: Reads, key: string, fn: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const read = fn(neverAborted());
    reads.under.set(key, read);
    reads.newest.set(key, read);
    const done = () => void (reads.under.get(key) === read && reads.under.delete(key));
    read.then((data) => {
        if (reads.newest.get(key) === read) cache.set(key, { data, at: Date.now() });
        done();
    }, done);
    return read;
}

/** What the newest read of `key` returns: one superseded while it was awaited hands over to the read after it. */
async function newestOf<T>(reads: Reads, key: string, read: Promise<T>): Promise<T> {
    for (;;) {
        const outcome = await read.then(
            (value) => ({ value }),
            (error: unknown) => ({ error })
        );
        const newer = reads.newest.get(key) as Promise<T> | undefined;
        if (!newer || newer === read) {
            if ('error' in outcome) throw outcome.error;
            return outcome.value;
        }
        read = newer;
    }
}

/** A read of `key`: `join` shares the one under way (a mount, a focus), else one begins (a refresh after a write). */
function readKey<T>(cache: Map<string, Entry>, key: string, fn: (signal: AbortSignal) => Promise<T>, join: boolean): Promise<T> {
    const reads = readsOf(cache);
    const under = join ? (reads.under.get(key) as Promise<T> | undefined) : undefined;
    return newestOf(reads, key, under ?? begin(cache, reads, key, fn));
}

/** The value a read of `key` through `client` last returned, if any. */
export function peekV1<T>(client: object, key: string): T | undefined {
    return cacheFor(client).get(key)?.data as T | undefined;
}

/** Puts a value kept from an earlier visit (in this browser) in the cache for `key` unless it holds one already, as
 *  old as can be: a view paints it at once and reads it again. */
export function primeV1<T>(client: object, key: string, data: T): void {
    const cache = cacheFor(client);
    if (!cache.has(key)) cache.set(key, { data, at: 0 });
}

/** Reads `key` into the cache outside a view (or joins the read under way), as a mounted `useV1` would. */
export function readV1<T>(client: object, key: string, fn: () => Promise<T>): Promise<T> {
    return readKey(cacheFor(client), key, fn, true);
}

/** Reads `key` ahead of the view that shows it (a hover, the likely next click), unless one landed in the last
 *  `freshMs`: the view then paints from the cache, or takes the read still under way. */
export function prefetchV1<T>(client: object, key: string, fn: () => Promise<T>, freshMs = 5000): void {
    const cached = cacheFor(client).get(key);
    if (cached && Date.now() - cached.at < freshMs) return;
    readV1(client, key, fn).catch((e: unknown) => console.warn('[v1] prefetch failed:', key, e));
}

/** Revalidate every mounted read whose key starts with `prefix` (call after a successful write). A read still under
 *  way began before the write: none is shared or kept after it. */
export function invalidateV1(prefix: string): void {
    for (const { under, newest } of allReads) {
        for (const key of [...under.keys()]) if (key.startsWith(prefix)) under.delete(key);
        for (const key of [...newest.keys()]) if (key.startsWith(prefix)) newest.delete(key);
    }
    for (const [key, set] of revalidators) if (key.startsWith(prefix)) set.forEach((fn) => fn());
}

export function useV1<T>(key: string | null, fn: (signal: AbortSignal) => Promise<T>, options: V1Options = {}): V1State<T> {
    const provided = useProvidedClient();
    const client = options.client ?? provided;
    if (!client) throw new Error('useV1() needs a client: under a <ClientProvider>, or as options.client.');
    const cache = cacheFor(client);
    const active = (options.enabled ?? true) && key !== null;
    const fnRef = useRef(fn);
    fnRef.current = fn;
    const [state, setState] = useState<{ key: string | null; data: T | undefined; error: unknown; pending: boolean }>(() => ({
        key,
        data: key ? (cache.get(key)?.data as T | undefined) : undefined,
        error: undefined,
        pending: active,
    }));
    const seq = useRef(0);
    const lastFocusRun = useRef(0);

    // A new key shows its own cached value, never the previous key's.
    const current =
        state.key === key
            ? state
            : { key, data: key ? (cache.get(key)?.data as T | undefined) : undefined, error: undefined, pending: active };

    /** `join`: take a read of the key already under way (a mount, a focus); a refresh after a write starts its own. */
    const read = useCallback(async (join: boolean) => {
        if (!active || key === null) return;
        const id = ++seq.current;
        setState((s) => (s.key === key ? { ...s, error: undefined, pending: true } : { key, data: cache.get(key)?.data as T | undefined, error: undefined, pending: true }));
        try {
            const data = await readKey(cache, key, (signal) => fnRef.current(signal), join);
            if (id !== seq.current) return;
            setState({ key, data, error: undefined, pending: false });
        } catch (error) {
            if (id !== seq.current) return;
            setState((s) => ({ key, data: s.key === key ? s.data : undefined, error, pending: false }));
        }
    }, [active, key, cache]);
    const refresh = useCallback(() => read(false), [read]);

    useEffect(() => {
        void read(true);
        return () => {
            seq.current++;
        };
    }, [read]);

    useEffect(() => {
        if (!active || key === null) return;
        // Returning to a tab fires both focus and visibilitychange: one revalidation, not two.
        const onFocus = () => {
            if (document.hidden || Date.now() - lastFocusRun.current < FOCUS_DEDUPE_MS) return;
            lastFocusRun.current = Date.now();
            void read(true);
        };
        window.addEventListener('focus', onFocus);
        document.addEventListener('visibilitychange', onFocus);
        let set = revalidators.get(key);
        if (!set) revalidators.set(key, (set = new Set()));
        // invalidateV1 drops the reads begun before its write, so the views it revalidates share one read after it.
        const run = () => void read(true);
        set.add(run);
        const timer = options.pollMs
            ? window.setInterval(() => {
                  if (!document.hidden) void read(true);
              }, options.pollMs)
            : undefined;
        return () => {
            window.removeEventListener('focus', onFocus);
            document.removeEventListener('visibilitychange', onFocus);
            set!.delete(run);
            if (!set!.size) revalidators.delete(key);
            if (timer !== undefined) window.clearInterval(timer);
        };
    }, [active, key, read, options.pollMs]);

    const mutate = useCallback(
        (data: T) => {
            if (key === null) return;
            // The value from now: a read begun before it hands over to it rather than landing over it.
            const reads = readsOf(cache);
            reads.under.delete(key);
            reads.newest.set(key, Promise.resolve(data));
            cache.set(key, { data, at: Date.now() });
            setState({ key, data, error: undefined, pending: false });
        },
        [key, cache]
    );

    return {
        data: current.data,
        error: current.error,
        loading: current.pending && current.data === undefined && current.error === undefined,
        refresh,
        mutate,
    };
}
