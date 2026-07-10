// Light/dark theme management for the authed app. The preference is stored in
// localStorage and applied as a `dark` class on <html> (tailwind darkMode:
// 'class'). Only the dashboard honors the preference — marketing, blog, and
// public pages stay dark (their components are tokenized with dark: pins, so
// forcing the class renders the original dark design exactly).

export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'nc-theme';
export const THEME_CHANGE_EVENT = 'noclick:theme-change';

// Keep in sync with the no-flash inline script in root.tsx. Only /dashboard
// (which hosts the workflow editor + canvas + settings + usage) is themed.
const THEMED_PATH_RE = /^\/dashboard(\/|$)/;

export function isThemedPath(pathname: string): boolean {
    return THEMED_PATH_RE.test(pathname);
}

export function getStoredTheme(): Theme {
    if (typeof window === 'undefined') return 'dark';
    try {
        return window.localStorage.getItem(THEME_STORAGE_KEY) === 'light'
            ? 'light'
            : 'dark';
    } catch {
        return 'dark';
    }
}

/** Sync <html>'s `dark` class with the stored preference for the current route. */
export function applyTheme(pathname = window.location.pathname): void {
    const dark = !isThemedPath(pathname) || getStoredTheme() === 'dark';
    document.documentElement.classList.toggle('dark', dark);
}

export function setTheme(theme: Theme): void {
    try {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
        // Storage unavailable (private mode) — the flip still applies this session.
    }
    applyTheme();
    window.dispatchEvent(
        new CustomEvent(THEME_CHANGE_EVENT, { detail: theme })
    );
}
