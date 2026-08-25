// Tracks the ACTUAL rendered theme — the `dark` class on <html> — not the
// stored preference. Routes outside the /dashboard theme gate render dark even
// with a light preference stored, so components that must match what's on
// screen (canvas SVG colors, sticky tints, monochrome brand-icon inversion)
// key off this. Re-renders on every toggle via a MutationObserver.
import { useEffect, useState } from 'react';

export function useIsDark(): boolean {
    const [isDark, setIsDark] = useState(() =>
        typeof document === 'undefined'
            ? true
            : document.documentElement.classList.contains('dark')
    );
    useEffect(() => {
        const el = document.documentElement;
        const update = () => setIsDark(el.classList.contains('dark'));
        update();
        const mo = new MutationObserver(update);
        mo.observe(el, { attributes: true, attributeFilter: ['class'] });
        return () => mo.disconnect();
    }, []);
    return isDark;
}
