// A row of pills kept to one line: when its items outgrow the room, the lowest-ranked of them fold to their icons, one
// at a time, and unfold as room comes back. Each item marks its place with `data-fold` (its rank: 0 folds first) inside
// the row's inner strip, which is as wide as its items; the row itself clips. Measured, never guessed: an item's width
// before it folded is kept, so it unfolds only where it fits again, and every change to the room or the items (a label
// read late, a pill appearing) is judged again before it paints.
import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';

export interface FitRow {
    /** The clipping row. */
    row: React.RefObject<HTMLDivElement | null>;
    /** The strip inside it, as wide as its items. */
    inner: React.RefObject<HTMLDivElement | null>;
    /** Whether the item of `rank` is folded to its icon now. */
    folded: (rank: number) => boolean;
}

/** The next set of folded ranks for what the row measures now, or null when it already fits as it should. */
export function nextFold(
    room: number,
    need: number,
    items: readonly { rank: number; width: number }[],
    folded: readonly number[],
    unfolded: ReadonlyMap<number, number>
): number[] | null {
    const present = folded.filter((r) => items.some((i) => i.rank === r));
    if (present.length !== folded.length) return present;
    const ordered = [...items].sort((a, b) => a.rank - b.rank);
    if (need > room + 0.5) {
        const next = ordered.find((i) => !folded.includes(i.rank));
        return next ? [...folded, next.rank] : null;
    }
    const last = [...ordered].reverse().find((i) => folded.includes(i.rank));
    const full = last && unfolded.get(last.rank);
    if (last && full !== undefined && need - last.width + full <= room + 0.5) return folded.filter((r) => r !== last.rank);
    return null;
}

/** `enabled` false (a phone, where the row wraps instead) folds nothing. */
export function useFitRow(enabled: boolean): FitRow {
    const row = useRef<HTMLDivElement>(null);
    const inner = useRef<HTMLDivElement>(null);
    const [folded, setFolded] = useState<number[]>([]);
    const now = useRef(folded);
    now.current = folded;
    // Each folded item's width just before it folded.
    const unfolded = useRef(new Map<number, number>());

    const judge = useCallback((): number[] | null => {
        const r = row.current;
        const i = inner.current;
        if (!enabled || !r || !i) return now.current.length ? [] : null;
        // Fractional widths, never rounded ones: each rounded alone, an item and the strip it sits in can disagree by a
        // pixel, so the row folds an item that then measures as fitting again, forever.
        const width = (el: HTMLElement) => el.getBoundingClientRect().width;
        const items = [...i.querySelectorAll<HTMLElement>('[data-fold]')].map((el) => ({ rank: Number(el.dataset.fold), width: width(el) }));
        const next = nextFold(width(r), width(i), items, now.current, unfolded.current);
        if (next) for (const rank of next) if (!now.current.includes(rank)) unfolded.current.set(rank, items.find((x) => x.rank === rank)?.width ?? 0);
        return next;
    }, [enabled]);

    // After every render of the row: one step at a time, each its own render, until it fits (`nextFold` settles).
    // eslint-disable-next-line react-hooks/exhaustive-deps -- every render is judged; it stops once nothing changes
    useLayoutEffect(() => {
        const next = judge();
        if (next) setFolded(next);
    });

    useLayoutEffect(() => {
        if (!enabled || typeof ResizeObserver === 'undefined') return;
        const watch = new ResizeObserver(() => {
            const next = judge();
            if (next) flushSync(() => setFolded(next));
        });
        if (row.current) watch.observe(row.current);
        if (inner.current) watch.observe(inner.current);
        return () => watch.disconnect();
    }, [enabled, judge]);

    return { row, inner, folded: (rank) => folded.includes(rank) };
}
