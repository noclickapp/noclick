// Light/dark theme management. The preference is stored in localStorage and
// applied as a `dark` class on <html> (tailwind darkMode: 'class'). Themed paths
// honor it; every other page stays dark (its components are tokenized with dark:
// pins, so forcing the class renders the original dark design exactly).

export type Theme = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'nc-theme';
export const THEME_CHANGE_EVENT = 'noclick:theme-change';

// The engine's own themed paths: /dashboard (the workflow editor + canvas +
// settings + usage), /b (the public builder input bridge, which carries its own
// toggle) and /credential/provide. A deployment adds the pages it builds for both
// themes with registerThemedPaths (the hosted site's in cloud/bootstrap.ts). The
// no-flash inline script in root.tsx tests the same patterns (themedPathSources).
const THEMED_PATH_RE = /^\/(?:dashboard|b|credential\/provide)(?:\/|$)/;
const registeredThemedPaths: RegExp[] = [];

/** Idempotent: a dev server re-runs the registering module on every reload, and a repeat would make the server's
 *  inline script differ from the browser's. */
export function registerThemedPaths(pattern: RegExp): void {
    if (!registeredThemedPaths.some((p) => p.source === pattern.source)) registeredThemedPaths.push(pattern);
}

export function isThemedPath(pathname: string): boolean {
    return THEMED_PATH_RE.test(pathname) || registeredThemedPaths.some((pattern) => pattern.test(pathname));
}

/** Every themed pattern's source, for the inline script that applies the theme before hydration. */
export function themedPathSources(): string[] {
    return [THEMED_PATH_RE.source, ...registeredThemedPaths.map((pattern) => pattern.source)];
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

/** The theme actually rendered right now (the `.dark` class on <html>), not the
 * stored preference. On non-themed routes this is always 'dark'; on themed routes
 * it reflects the resolved preference. Use this to tell the AI builder which theme
 * the user is looking at so generated UIs match the surface, not a mismatched pref. */
export function getAppliedTheme(): 'light' | 'dark' {
    if (typeof document === 'undefined') return 'dark';
    return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
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
