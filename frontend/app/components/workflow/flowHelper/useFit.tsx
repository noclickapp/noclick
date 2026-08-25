// Priority+ navigation pattern. Iteratively folds the lowest-priority item
// to its compact representation until the container stops overflowing; on
// resize the set resets so items get a chance to restore.
//
// Requires the container to be a flex row (or any layout where overflow
// shows up in scrollWidth) — grid columns with minmax(0,1fr) silently
// shrink below content and the overlap never surfaces in scrollWidth.

import {
    RefObject,
    useEffect,
    useLayoutEffect,
    useState,
} from 'react';

export interface FitItem<K extends string = string> {
    key: K;
    /** Lower priority collapses first when the strip overflows. */
    priority: number;
}

export function useFit<K extends string>(
    containerRef: RefObject<HTMLElement | null>,
    items: ReadonlyArray<FitItem<K>>,
) {
    const [compactSet, setCompactSet] = useState<Set<K>>(() => new Set());

    // After every render, if the container overflows, add the next
    // lowest-priority uncompacted item. React re-renders, useLayoutEffect
    // runs again, repeat until fits. Converges in at most items.length steps.
    useLayoutEffect(() => {
        const container = containerRef.current;
        if (!container || container.clientWidth === 0) return;
        if (container.scrollWidth <= container.clientWidth + 1) return;
        const next = items
            .filter(i => !compactSet.has(i.key))
            .sort((a, b) => a.priority - b.priority)[0];
        if (!next) return;
        setCompactSet(prev => new Set([...prev, next.key]));
    });

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        const ro = new ResizeObserver(() => {
            setCompactSet(prev => (prev.size === 0 ? prev : new Set()));
        });
        ro.observe(container);
        return () => ro.disconnect();
    }, [containerRef]);

    const isCompact = (key: K): boolean => compactSet.has(key);
    return { compactSet, isCompact };
}
