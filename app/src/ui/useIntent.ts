// Reads ahead what a click would open: a row's handlers that call `ahead(id)` once the pointer rests on it (or it takes
// focus), so a sweep of the mouse down a list asks for nothing and a click after a hover finds its view already read. A
// finger never rests: it reads ahead as it lands, the moment before its tap.
import { useCallback, useEffect, useRef } from 'react';

/** How long the pointer rests on a row before it counts as intent. */
const REST_MS = 60;

/** A row's handlers that read ahead what it opens. */
export type Intent = (id: string) => { onPointerEnter: () => void; onPointerLeave: () => void; onPointerDown: () => void; onFocus: () => void };

export function useIntent(ahead: (id: string) => void): Intent {
    const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const latest = useRef(ahead);
    latest.current = ahead;
    useEffect(() => () => clearTimeout(timer.current), []);
    return useCallback(
        (id: string) => ({
            onPointerEnter: () => {
                clearTimeout(timer.current);
                timer.current = setTimeout(() => latest.current(id), REST_MS);
            },
            onPointerLeave: () => clearTimeout(timer.current),
            onPointerDown: () => {
                clearTimeout(timer.current);
                latest.current(id);
            },
            onFocus: () => latest.current(id),
        }),
        []
    );
}
