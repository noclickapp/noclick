// Light/dark theme management for the main app. The preference is stored in
// localStorage and applied as a `dark` class on <html> (tailwind darkMode:
// 'class'). Only converted app routes honor the preference — marketing pages
// and the workflow canvas are still hardcoded-dark, so they keep the `dark`
// class regardless until their components are migrated to semantic tokens.

export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'nc-theme';
export const THEME_CHANGE_EVENT = 'noclick:theme-change';

// Keep in sync with the no-flash inline script in root.tsx. Only the authed
// dashboard (which hosts the workflow editor + canvas) is themed; public pages
// like /workflow/<slug> templates and /share use LandingNav and stay dark.
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
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}
