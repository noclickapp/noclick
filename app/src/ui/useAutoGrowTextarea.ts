// A textarea that grows with its text up to a cap, then scrolls inside.
// Hidden mounts measure NOTHING: an interface block kept alive behind another
// mounts display:none, scrollHeight reads 0, and the pinned 0px height survived
// the reveal as a squished composer — so measurement skips while hidden and a
// ResizeObserver re-fires it on the 0→real flip.
import { useEffect, type RefObject } from 'react';

export function useAutoGrowTextarea(ref: RefObject<HTMLTextAreaElement | null>, value: string, maxHeight: number): void {
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const measure = () => {
            // display:none ancestor → offsetParent null → nothing to measure.
            if (el.offsetParent === null) return;
            el.style.height = 'auto';
            el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
        };
        measure();
        if (typeof ResizeObserver === 'undefined') return;
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        return () => ro.disconnect();
    }, [value, ref, maxHeight]);
}
