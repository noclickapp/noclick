// Detects whether the client is macOS so UI can show ⌘ vs Ctrl in keyboard
// hints. Starts `false` to avoid SSR hydration mismatch, then resolves on mount.
// Shared so every keybinding preview (KeyHint) agrees on the platform glyph.
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

/** Platform label for the modifier key in inline text hints: '⌘' on macOS,
 *  'Ctrl' elsewhere. Single source of truth so callers never inline the
 *  isMac check. For keycap chips use <KeyHint keys={['mod', …]} /> instead. */
export function useModKey(): string {
    return useIsMac() ? '⌘' : 'Ctrl';
}
