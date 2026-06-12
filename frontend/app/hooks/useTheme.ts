// React binding for the theme preference: returns the stored theme plus a
// setter that flips <html>'s `dark` class immediately and notifies every
// subscribed component (same-tab via a custom event, cross-tab via `storage`).
import { useEffect, useState } from 'react';
import {
    getStoredTheme,
    setTheme,
    THEME_CHANGE_EVENT,
    type Theme,
} from '~/lib/theme';

export function useTheme(): [Theme, (theme: Theme) => void] {
    const [theme, setThemeState] = useState<Theme>(getStoredTheme);

    useEffect(() => {
        const sync = () => setThemeState(getStoredTheme());
        window.addEventListener(THEME_CHANGE_EVENT, sync);
        window.addEventListener('storage', sync);
        return () => {
            window.removeEventListener(THEME_CHANGE_EVENT, sync);
            window.removeEventListener('storage', sync);
        };
    }, []);

    return [theme, setTheme];
}
