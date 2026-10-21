// Values keyed by node type (a node's schema, its definition), each loaded once on first ask, so a page fetches
// only the types it shows. Reads are synchronous over what has loaded; listeners hear each load call settle,
// which is how useLazyTypes re-renders a reader. Legacy types resolve to the type that replaced them.
import { resolveNodeType } from '~/utils/nodeMeta';

export interface LazyTypeStore<V> {
    /** What has loaded so far, by type. */
    readonly values: Readonly<Record<string, V>>;
    /** Whether every listed type has loaded (a type with nothing to load counts as loaded). */
    loaded(types: Iterable<string | null | undefined>): boolean;
    /** Loads the listed types (each once; a type with nothing to load is skipped). */
    load(types: Iterable<string | null | undefined>): Promise<void>;
    /** Whether the type has something to load. */
    knows(type: string): boolean;
    /** Puts values already in hand (an eager import). */
    put(values: Record<string, V>): void;
    subscribe(listener: () => void): () => void;
    /** Bumps each time a load call settles. */
    version(): number;
}

export function createLazyTypeStore<V>(loaderFor: (type: string) => (() => Promise<V>) | undefined): LazyTypeStore<V> {
    const values: Record<string, V> = {};
    const loading = new Map<string, Promise<void>>();
    const listeners = new Set<() => void>();
    let version = 0;
    // Readers re-render once per load call, not once per value (a walk of every type lands ~165).
    const notify = () => {
        version += 1;
        listeners.forEach((listener) => listener());
    };
    const pendingType = (raw: string | null | undefined): string | null => {
        if (!raw) return null;
        const type = resolveNodeType(raw);
        return type in values || !loaderFor(type) ? null : type;
    };

    return {
        values,
        loaded(types) {
            for (const raw of types) if (pendingType(raw)) return false;
            return true;
        },
        load(types) {
            const pending: Promise<void>[] = [];
            for (const raw of types) {
                const type = pendingType(raw);
                if (!type) continue;
                let inFlight = loading.get(type);
                if (!inFlight) {
                    inFlight = loaderFor(type)!()
                        .then((value) => {
                            values[type] = value;
                        })
                        .finally(() => loading.delete(type));
                    loading.set(type, inFlight);
                }
                pending.push(inFlight);
            }
            if (!pending.length) return Promise.resolve();
            return Promise.all(pending)
                .finally(notify)
                .then(() => undefined);
        },
        knows: (type) => !!loaderFor(resolveNodeType(type)),
        put(given) {
            Object.assign(values, given);
            notify();
        },
        subscribe(listener) {
            listeners.add(listener);
            return () => listeners.delete(listener);
        },
        version: () => version,
    };
}
