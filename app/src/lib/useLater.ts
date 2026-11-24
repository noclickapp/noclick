// Work a component puts off from a handler (focus a field once it's drawn, record an edit a task later, pan once
// a step is measured), dropped when the component unmounts: run after, it would act on a screen that's gone. A handler
// that awaits something and asks for it only after the component has gone gets nothing scheduled.
import { useCallback, useEffect, useRef } from 'react';

function usePending<Id>(cancel: (id: Id) => void) {
    const pending = useRef(new Set<Id>());
    const gone = useRef(false);
    useEffect(() => {
        const ids = pending.current;
        gone.current = false;
        return () => {
            gone.current = true;
            ids.forEach(cancel);
            ids.clear();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return { pending, gone };
}

/** `later(fn, ms)`: `fn` after `ms`, unless the component has unmounted by then. Stable for the component's life. */
export function useLater(): (fn: () => void, ms?: number) => void {
    const { pending, gone } = usePending<ReturnType<typeof setTimeout>>((timer) => clearTimeout(timer));
    return useCallback((fn: () => void, ms = 0) => {
        if (gone.current) return;
        const timer = setTimeout(() => {
            pending.current.delete(timer);
            fn();
        }, ms);
        pending.current.add(timer);
    }, [pending, gone]);
}

/** `nextFrame(fn)`: `fn` on the next animation frame, unless the component has unmounted by then. Stable. */
export function useNextFrame(): (fn: () => void) => void {
    const { pending, gone } = usePending<number>((frame) => cancelAnimationFrame(frame));
    return useCallback((fn: () => void) => {
        if (gone.current) return;
        const frame = requestAnimationFrame(() => {
            pending.current.delete(frame);
            fn();
        });
        pending.current.add(frame);
    }, [pending, gone]);
}
