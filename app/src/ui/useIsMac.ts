// Detects whether the client is macOS (⌘ or Ctrl, for the keyboard shortcuts page and the keys the app listens for).
// Starts `false` to avoid SSR hydration mismatch, then resolves on mount.
import { useEffect, useState } from 'react';

export function useIsMac(): boolean {
    const [isMac, setIsMac] = useState(false);
    useEffect(() => {
        if (typeof navigator === 'undefined') return;
        // navigator.platform is deprecated but still the most reliable signal in
        // practice; fall back to userAgent for browsers that nuke it.
        const platform = navigator.platform || navigator.userAgent || '';
        setIsMac(/Mac|iPhone|iPad|iPod/.test(platform));
    }, []);
    return isMac;
}
