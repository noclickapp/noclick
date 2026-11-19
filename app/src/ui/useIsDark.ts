// Tracks the ACTUAL rendered theme — the `dark` class on <html> — not the
// stored preference. Routes outside the theme gate render dark even with a
// light preference stored, so components that must match what's on screen
// (canvas SVG colors, sticky tints, monochrome brand-icon inversion) key off
// this. Re-renders on every toggle via a MutationObserver.
//
// The server renders dark, so hydration reads dark too (no mismatch on a
// light page) and React re-renders with the real class straight after; a
// component mounted later reads the class directly.
import { useSyncExternalStore } from 'react';

function subscribe(onChange: () => void): () => void {
    const observer = new MutationObserver(onChange);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
}

const isDarkNow = () => document.documentElement.classList.contains('dark');
const isDarkOnServer = () => true;

export function useIsDark(): boolean {
    return useSyncExternalStore(subscribe, isDarkNow, isDarkOnServer);
}
