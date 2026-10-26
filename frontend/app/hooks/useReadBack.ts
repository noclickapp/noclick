// What the chat's cards read back by id over the socket (the coordinator's jobs, its reminders): once for each set of
// ids, again whenever `nudge` changes (a new turn), and every few seconds while an item is moving. A server that never
// answered the read (one older than it) isn't asked again on this page, and `live` stays false: the cards then say
// only what their tool reported.
import { useEffect, useRef, useState } from 'react';

const POLL_MS = 5000;
export const READ_TIMEOUT_MS = 10_000;
// A read takes at most this many; a thread with more follows its latest.
const MAX_IDS = 50;

export interface ReadBack<T> {
    /** Whether this server reads them back at all. */
    live: boolean;
    byId: Record<string, T>;
}

export interface ReadBackOptions<T> {
    /** Another id an item read hands its wait on to, read with the rest. */
    follow?: (item: T) => string | undefined;
    /** Whether an item is still moving, so the read repeats on a timer. */
    moving?: (item: T) => boolean;
}

/** Reads `ids` with `read` (a module-level function), keyed by `idOf`. */
export function useReadBack<T>(
    ids: readonly string[],
    nudge: unknown,
    read: (ids: [string, ...string[]]) => Promise<T[]>,
    idOf: (item: T) => string,
    { follow, moving }: ReadBackOptions<T> = {}
): ReadBack<T> {
    const [state, setState] = useState<ReadBack<T>>({ live: false, byId: {} });
    const answered = useRef(false);
    const unanswered = useRef(false);
    const items = Object.values(state.byId);
    const followed = follow
        ? items.map(follow).filter((id): id is string => !!id)
        : [];
    const key = [...new Set([...ids, ...followed])].slice(-MAX_IDS).join(',');
    const poll = !!moving && items.some(moving);

    useEffect(() => {
        if (!key || unanswered.current) return;
        let cancelled = false;
        const once = async () => {
            try {
                const found = await read(
                    key.split(',') as [string, ...string[]]
                );
                if (cancelled) return;
                answered.current = true;
                setState({
                    live: true,
                    byId: Object.fromEntries(
                        found.map((item) => [idOf(item), item])
                    ),
                });
            } catch (error) {
                if (cancelled) return;
                if (!answered.current) unanswered.current = true;
                console.warn('[coordinator] read back failed:', error);
            }
        };
        void once();
        const timer = poll
            ? window.setInterval(() => void once(), POLL_MS)
            : undefined;
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [key, poll, nudge, read, idOf]);

    return state;
}
