// Light/dark theme management. The preference is stored in localStorage and
// applied as a `dark` class on <html> (tailwind darkMode: 'class'). Every
// route honors the preference — components style with semantic tokens
// (bg-background/card/popover, text-foreground/…) so both themes render from
// one markup. Deliberate dark islands (code editors, on-artwork overlays)
// opt out locally.

export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'nc-theme';
export const THEME_CHANGE_EVENT = 'noclick:theme-change';

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

/** Sync <html>'s `dark` class with the stored preference. */
export function applyTheme(): void {
    document.documentElement.classList.toggle('dark', getStoredTheme() === 'dark');
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
