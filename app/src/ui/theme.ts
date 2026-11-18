// Light/dark theme management. The preference is stored in localStorage and
// applied as a `dark` class on <html> (tailwind darkMode: 'class'). An app whose
// pages are all built for both themes says nothing more: every page honours it.
// One that also has pages built for dark alone names the themed ones
// (registerThemedPaths): only those honour the preference, the rest stay dark.

export type Theme = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'nc-theme';
export const THEME_CHANGE_EVENT = 'noclick:theme-change';

// The pages built for both themes, where an app names them; none named means all of them. The no-flash script
// (themeInitScript) tests the same patterns.
const registeredThemedPaths: RegExp[] = [];

/** Names pages built for both themes, from the module the app's root imports first. Idempotent: a dev server re-runs
 *  the registering module on every reload, and a repeat would make the server's inline script differ from the
 *  browser's. */
export function registerThemedPaths(pattern: RegExp): void {
    if (!registeredThemedPaths.some((p) => p.source === pattern.source)) registeredThemedPaths.push(pattern);
}

export function isThemedPath(pathname: string): boolean {
    return registeredThemedPaths.length === 0 || registeredThemedPaths.some((pattern) => pattern.test(pathname));
}

/** Every themed pattern's source, in the order they were named. */
export function themedPathSources(): string[] {
    return registeredThemedPaths.map((pattern) => pattern.source);
}

/** The script for the document's head that applies a stored light preference before first paint, so a page never
 *  flashes dark. Inline because it runs before any bundle; built once the themed pages are named. */
export function themeInitScript(): string {
    const sources = themedPathSources();
    const themed = sources.length ? `&&${JSON.stringify(sources)}.some(function(s){return new RegExp(s).test(location.pathname)})` : '';
    return `try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');if((t==='light'||(t==='system'&&!matchMedia('(prefers-color-scheme: dark)').matches))${themed}){document.documentElement.classList.remove('dark')}}catch(e){}`;
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
 * stored preference. On a page that isn't themed this is always 'dark'; on a themed
 * one it reflects the resolved preference. For anything that must match what the
 * person is looking at rather than what they chose. */
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
