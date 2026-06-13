// Tracks an element's rendered width via ResizeObserver. Returns a ref to
// attach and the latest measured width (0 until first measurement). Used for
// container-query-style responsiveness where a fixed viewport breakpoint is
// the wrong reference frame (e.g. a navbar narrowed by side panels).
import { useEffect, useRef, useState } from 'react';

export function useElementWidth<T extends HTMLElement = HTMLDivElement>(): [
    React.RefObject<T | null>,
    number,
] {
    const ref = useRef<T>(null);
    const [width, setWidth] = useState(0);

    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const update = () => setWidth(el.getBoundingClientRect().width);
        update();
        const observer = new ResizeObserver(update);
        observer.observe(el);
        return () => observer.disconnect();
    }, []);

    return [ref, width];
}
