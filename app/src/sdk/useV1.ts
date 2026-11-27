// The read cache: a hook for /v1 reads that serves the cached value at once, then revalidates on mount, on focus, on
// an interval (paused while the tab is hidden) and on invalidateV1() after a write. The cache is per client, so two
// clients (the app's and a fixture lab's) never mix.
//
// Where the account's change stream follows a client (watchLive.ts), the stream says what to read again: a page coming
// back into view reads nothing of its own accord, since the stream carries on from its last change (or says reset).
//
// A host can keep a client's reads in this browser between visits (`keepReads`, per account): the reads a screen marks
// (`keepRead`) open on what they read last, as old as can be, and read again behind it.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { JsonObject, NoClick, Page } from 'noclick';
import { useProvidedClient } from '@/sdk/client';
import { keepFor, keepWhenLeaving, readKept } from '@/lib/kept';

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
    /** When it was read; 0 for a value from an earlier visit, not read again on this page yet. */
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

// ── Keeping reads between visits ─────────────────────────────────────────────

/** How a read is kept in this browser: the plain data stored (objects, arrays, strings, numbers, booleans, dates), and
 *  the value that stands for it again. A read whose stored form isn't plain data isn't kept. */
export interface KeptAs<T> {
    store: (data: T) => unknown;
    revive: (stored: unknown, client: NoClick) => T;
}

/** A read whose value is plain data, kept as it is. */
export const AS_IS: KeptAs<unknown> = { store: (data) => data, revive: (stored) => stored };

/** A page of the SDK's objects, kept as their JSON and made again with `make`. */
export function asPage<T extends { toJSON(): JsonObject }>(make: (raw: JsonObject, client: NoClick) => T): KeptAs<Page<T>> {
    return {
        store: (page) => ({ data: page.data.map((item) => item.toJSON()), nextCursor: page.nextCursor }),
        revive: (stored, client) => {
            const page = stored as { data: JsonObject[]; nextCursor: string | null };
            return { data: page.data.map((raw) => make(raw, client)), nextCursor: page.nextCursor };
        },
    };
}

const ways: { matches: (key: string) => boolean; as: KeptAs<unknown> }[] = [];

/** Keeps the reads `key` names (that key, or every key a test passes) in this browser between visits, where the host
 *  keeps a client's reads (`keepReads`). Declared once, beside the read. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- each read keeps its own type
export function keepRead(key: string | ((key: string) => boolean), as: KeptAs<any> = AS_IS): void {
    ways.push({ matches: typeof key === 'string' ? (k) => k === key : key, as });
}

const wayOf = (key: string) => ways.find((way) => way.matches(key))?.as;

/** Bumped when what's stored changes shape: a copy of another version is dropped. */
const READS_VERSION = 1;
/** A read whose stored form is longer than this isn't kept (a long thread's history, a big listing). */
const MAX_STORED_CHARS = 300_000;
/** How many reads are kept, the most recently read first, and for how long one is kept unread. */
const MAX_STORED = 150;
const KEPT_FOR_MS = 30 * 24 * 3600_000;
const SAVE_AFTER_MS = 2000;

interface Stored {
    value: unknown;
    at: number;
}

interface Keeping {
    client: NoClick;
    account: string;
    /** What this browser holds, by key: restored from it, then kept as reads land. */
    stored: Map<string, Stored>;
    /** The value each stored form was made from, so a read that didn't change isn't stored again. */
    from: Map<string, unknown>;
    restored: Promise<void>;
    timer: ReturnType<typeof setTimeout> | null;
}

const keepings = new WeakMap<object, Keeping>();
/** Views of a client showing nothing yet, by key: each takes a kept value that arrives after it drew. */
const waiting = new WeakMap<object, Map<string, Set<() => void>>>();

/** Plain data, as IndexedDB clones it, within a bound on its size. */
function plain(value: unknown, budget = { left: 100_000 }): boolean {
    if (value === null || value === undefined || ['string', 'number', 'boolean'].includes(typeof value)) return true;
    if (typeof value !== 'object' || --budget.left < 0) return false;
    if (value instanceof Date) return true;
    if (Array.isArray(value)) return value.every((v) => plain(v, budget));
    const proto = Object.getPrototypeOf(value);
    return (proto === Object.prototype || proto === null) && Object.values(value).every((v) => plain(v, budget));
}

/** The cache's entry for `key`: what a read returned, else what this browser kept of it (made again on first use). */
function entryOf(client: object, key: string): Entry | undefined {
    const cache = cacheFor(client);
    const known = cache.get(key);
    if (known) return known;
    const keeping = keepings.get(client);
    const stored = keeping?.stored.get(key);
    const as = stored && wayOf(key);
    if (!keeping || !stored || !as) return undefined;
    try {
        const entry = { data: as.revive(stored.value, keeping.client), at: 0 };
        cache.set(key, entry);
        return entry;
    } catch {
        keeping.stored.delete(key);
        return undefined;
    }
}

function save(keeping: Keeping): void {
    if (keeping.timer) clearTimeout(keeping.timer);
    keeping.timer = null;
    for (const [key, entry] of cacheFor(keeping.client)) {
        const as = wayOf(key);
        if (!as || entry.at === 0 || keeping.from.get(key) === entry.data) continue;
        keeping.from.set(key, entry.data);
        try {
            const value = as.store(entry.data);
            if (plain(value) && JSON.stringify(value).length <= MAX_STORED_CHARS) keeping.stored.set(key, { value, at: entry.at });
            else keeping.stored.delete(key);
        } catch {
            keeping.stored.delete(key);
        }
    }
    const newest = [...keeping.stored].sort(([, a], [, b]) => b.at - a.at).slice(0, MAX_STORED);
    keepFor(keeping.account, 'reads', READS_VERSION, Object.fromEntries(newest));
}

function saveSoon(client: object): void {
    const keeping = keepings.get(client);
    if (keeping && !keeping.timer) keeping.timer = setTimeout(() => save(keeping), SAVE_AFTER_MS);
}

/** Keeps `client`'s marked reads (`keepRead`) in this browser for `account`, and restores what was kept on an earlier
 *  visit: a view showing nothing yet draws it at once, and every one reads again behind it. Once per client; a client
 *  reading as someone else (a staff member viewing an account) is never kept. */
export function keepReads(client: NoClick, account: string): void {
    if (keepings.has(client)) return;
    const keeping: Keeping = { client, account, stored: new Map(), from: new Map(), restored: Promise.resolve(), timer: null };
    keepings.set(client, keeping);
    keeping.restored = readKept<Record<string, Stored>>(account, 'reads', READS_VERSION).then((kept) => {
        const now = Date.now();
        for (const [key, stored] of Object.entries(kept ?? {})) {
            if (now - stored.at > KEPT_FOR_MS || keeping.stored.has(key)) continue;
            keeping.stored.set(key, stored);
            // A view already showing this key's read has nothing to take; one showing nothing takes the kept value.
            if (!cacheFor(client).has(key) && entryOf(client, key)) waiting.get(client)?.get(key)?.forEach((take) => take());
        }
    });
    if (typeof window !== 'undefined') keepWhenLeaving(() => keeping.timer && save(keeping));
}

/** Settles once what this browser kept for `client` is in its cache (at once where nothing is kept): for a read made
 *  outside a view that draws a kept value before its own read answers. */
export function readsRestored(client: object): Promise<void> {
    return keepings.get(client)?.restored ?? Promise.resolve();
}

// ── Following ────────────────────────────────────────────────────────────────

const followed = new WeakSet<object>();

/** Whether the account's change stream follows `client` (watchLive.ts): while it does, a view coming back into view
 *  reads nothing again by itself, because the stream carries on from its last change, re-reading what moved, or says
 *  reset. */
export function followReads(client: object, on: boolean): void {
    if (on) followed.add(client);
    else followed.delete(client);
}

// ── Reads ────────────────────────────────────────────────────────────────────

/** Begins a read of `key`, the newest from now: its result goes into the cache unless a newer one began meanwhile. */
function begin<T>(client: object, reads: Reads, key: string, fn: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const read = fn(neverAborted());
    reads.under.set(key, read);
    reads.newest.set(key, read);
    const done = () => void (reads.under.get(key) === read && reads.under.delete(key));
    read.then((data) => {
        if (reads.newest.get(key) === read) {
            cacheFor(client).set(key, { data, at: Date.now() });
            saveSoon(client);
        }
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
function readKey<T>(client: object, key: string, fn: (signal: AbortSignal) => Promise<T>, join: boolean): Promise<T> {
    const reads = readsOf(cacheFor(client));
    const under = join ? (reads.under.get(key) as Promise<T> | undefined) : undefined;
    return newestOf(reads, key, under ?? begin(client, reads, key, fn));
}

/** The value a read of `key` through `client` last returned, if any; with `kept` (the default), also one from an earlier
 *  visit that this browser kept, or a host put in, and the page hasn't read again yet. */
export function peekV1<T>(client: object, key: string, kept = true): T | undefined {
    const entry = kept ? entryOf(client, key) : cacheFor(client).get(key);
    return entry && (kept || entry.at > 0) ? (entry.data as T) : undefined;
}

/** Puts a value kept from an earlier visit (in this browser) in the cache for `key` unless it holds one already, as
 *  old as can be: a view paints it at once and reads it again. */
export function primeV1<T>(client: object, key: string, data: T): void {
    const cache = cacheFor(client);
    if (!cache.has(key)) cache.set(key, { data, at: 0 });
}

/** Reads `key` into the cache outside a view (or joins the read under way), as a mounted `useV1` would. */
export function readV1<T>(client: object, key: string, fn: () => Promise<T>): Promise<T> {
    return readKey(client, key, fn, true);
}

/** Reads `key` ahead of the view that shows it (a hover, the likely next click), unless one landed in the last
 *  `freshMs`: the view then paints from the cache, or takes the read still under way. */
export function prefetchV1<T>(client: object, key: string, fn: () => Promise<T>, freshMs = 5000): void {
    const cached = entryOf(client, key);
    if (cached && Date.now() - cached.at < freshMs) return;
    readV1(client, key, fn).catch((e: unknown) => console.warn('[v1] prefetch failed:', key, e));
}

/** The views a burst of invalidations asked to read again: each reads once, so a write, a frame and a reset at the
 *  same moment cost one read a view. */
let due: Set<() => void> | null = null;

/** Revalidate every mounted read whose key starts with `prefix` (call after a successful write). A read still under
 *  way began before the write: none is shared or kept after it. */
export function invalidateV1(prefix: string): void {
    for (const { under, newest } of allReads) {
        for (const key of [...under.keys()]) if (key.startsWith(prefix)) under.delete(key);
        for (const key of [...newest.keys()]) if (key.startsWith(prefix)) newest.delete(key);
    }
    if (!due) {
        const run = (due = new Set());
        queueMicrotask(() => {
            due = null;
            run.forEach((fn) => fn());
        });
    }
    for (const [key, set] of revalidators) if (key.startsWith(prefix)) set.forEach((fn) => due!.add(fn));
}

export function useV1<T>(key: string | null, fn: (signal: AbortSignal) => Promise<T>, options: V1Options = {}): V1State<T> {
    const provided = useProvidedClient();
    const client = options.client ?? provided;
    if (!client) throw new Error('useV1() needs a client: under a <ClientProvider>, or as options.client.');
    const cache = cacheFor(client);
    const active = (options.enabled ?? true) && key !== null;
    const fnRef = useRef(fn);
    fnRef.current = fn;
    const shown = (k: string | null) => (k ? (entryOf(client, k)?.data as T | undefined) : undefined);
    const [state, setState] = useState<{ key: string | null; data: T | undefined; error: unknown; pending: boolean }>(() => ({
        key,
        data: shown(key),
        error: undefined,
        pending: active,
    }));
    const seq = useRef(0);
    const lastFocusRun = useRef(0);

    // A new key shows its own cached value, never the previous key's.
    const current = state.key === key ? state : { key, data: shown(key), error: undefined, pending: active };

    /** `join`: take a read of the key already under way (a mount, a focus); a refresh after a write starts its own. */
    const read = useCallback(async (join: boolean) => {
        if (!active || key === null) return;
        const id = ++seq.current;
        setState((s) => (s.key === key ? { ...s, error: undefined, pending: true } : { key, data: entryOf(client, key)?.data as T | undefined, error: undefined, pending: true }));
        try {
            const data = await readKey(client, key, (signal) => fnRef.current(signal), join);
            if (id !== seq.current) return;
            setState({ key, data, error: undefined, pending: false });
        } catch (error) {
            if (id !== seq.current) return;
            setState((s) => ({ key, data: s.key === key ? s.data : undefined, error, pending: false }));
        }
    }, [active, key, client]);
    const refresh = useCallback(() => read(false), [read]);

    useEffect(() => {
        void read(true);
        return () => {
            seq.current++;
        };
    }, [read]);

    useEffect(() => {
        if (!active || key === null) return;
        // Returning to a tab fires both focus and visibilitychange: one revalidation, not two. None while the account's
        // change stream follows the client: it says what moved meanwhile.
        const onFocus = () => {
            if (document.hidden || followed.has(client) || Date.now() - lastFocusRun.current < FOCUS_DEDUPE_MS) return;
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
        // A value this browser kept, arriving after the view drew with none.
        let held = waiting.get(client);
        if (!held) waiting.set(client, (held = new Map()));
        let takers = held.get(key);
        if (!takers) held.set(key, (takers = new Set()));
        const take = () => setState((s) => (s.key === key && s.data === undefined ? { ...s, data: cache.get(key)?.data as T | undefined } : s));
        takers.add(take);
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
            takers!.delete(take);
            if (!takers!.size) held!.delete(key);
            if (timer !== undefined) window.clearInterval(timer);
        };
    }, [active, key, read, options.pollMs, client, cache]);

    const mutate = useCallback(
        (data: T) => {
            if (key === null) return;
            // The value from now: a read begun before it hands over to it rather than landing over it.
            const reads = readsOf(cache);
            reads.under.delete(key);
            reads.newest.set(key, Promise.resolve(data));
            cache.set(key, { data, at: Date.now() });
            saveSoon(client);
            setState({ key, data, error: undefined, pending: false });
        },
        [key, cache, client]
    );

    return {
        data: current.data,
        error: current.error,
        loading: current.pending && current.data === undefined && current.error === undefined,
        refresh,
        mutate,
    };
}
