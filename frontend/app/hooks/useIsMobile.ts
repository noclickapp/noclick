/*
Hooks for media-query-driven rendering. useMediaQuery subscribes to any CSS
media query (SSR-safe: false until hydration); useIsMobile is the standard
<768px viewport check used across components for mobile/desktop switching.
*/
import { useState, useEffect } from 'react';

export function useMediaQuery(query: string): boolean {
    const [matches, setMatches] = useState(false);

    useEffect(() => {
        // matchMedia fires `change` only when the query result actually flips,
        // not on every resize/scroll-driven viewport event (e.g. mobile URL-bar
        // collapse), so consumers re-render at most once per real change.
        // SSR stays `false` (initial state) for hydration parity; the client
        // flips it once.
        const mq = window.matchMedia(query);
        const update = () => setMatches(mq.matches);

        update();
        mq.addEventListener('change', update);
        return () => mq.removeEventListener('change', update);
    }, [query]);

    return matches;
}

export function useIsMobile(breakpoint: number = 768): boolean {
    // `max-width: ${breakpoint - 1}px` matches `innerWidth < breakpoint`.
    return useMediaQuery(`(max-width: ${breakpoint - 1}px)`);
}
