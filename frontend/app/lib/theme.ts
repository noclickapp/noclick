// Light/dark theme management for the authed app. The preference is stored in
// localStorage and applied as a `dark` class on <html> (tailwind darkMode:
// 'class'). Only the dashboard honors the preference — marketing, blog, and
// public pages stay dark (their components are tokenized with dark: pins, so
// forcing the class renders the original dark design exactly).

export type Theme = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'nc-theme';
export const THEME_CHANGE_EVENT = 'noclick:theme-change';

// Keep in sync with the no-flash inline script in root.tsx. /dashboard (the
// workflow editor + canvas + settings + usage) is themed, plus /b (the public
// builder input bridge — fully tokenized and carries its own subtle toggle
// for visitors who prefer light).
const THEMED_PATH_RE = /^\/(dashboard|b|credential\/provide)(\/|$)/;

export function isThemedPath(pathname: string): boolean {
    return THEMED_PATH_RE.test(pathname);
}

/** The user's stored choice — 'system' defers to prefers-color-scheme. The
 * absence of a stored value is 'dark' (the app's historical default), NOT
 * 'system', so existing users see no change until they pick. */
export function getStoredTheme(): Theme {
    if (typeof window === 'undefined') return 'dark';
    try {
        const v = window.localStorage.getItem(THEME_STORAGE_KEY);
        return v === 'light' || v === 'system' ? v : 'dark';
    } catch {
        return 'dark';
    }
}

/** The stored choice collapsed to what actually renders. */
export function resolveTheme(
    theme: Theme = getStoredTheme()
): 'light' | 'dark' {
    if (theme !== 'system') return theme;
    try {
        return window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light';
    } catch {
        return 'dark';
    }
}

/** Sync <html>'s `dark` class with the stored preference for the current route. */
export function applyTheme(pathname = window.location.pathname): void {
    const dark = !isThemedPath(pathname) || resolveTheme() === 'dark';
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

/** Re-applies the theme when the OS scheme flips while in 'system' mode.
 * Returns a cleanup fn; wired once from the root layout. */
export function watchSystemTheme(): () => void {
    try {
        const mq = window.matchMedia('(prefers-color-scheme: dark)');
        const onChange = () => {
            if (getStoredTheme() === 'system') {
                applyTheme();
                window.dispatchEvent(
                    new CustomEvent(THEME_CHANGE_EVENT, { detail: 'system' })
                );
            }
        };
        mq.addEventListener('change', onChange);
        return () => mq.removeEventListener('change', onChange);
    } catch {
        return () => {};
    }
}
