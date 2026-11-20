// The rows every palette's commands are built from, whoever builds them (the host's `shell.palette`, or the app's own
// standard): what a page handed over, what a registered source added, the theme, the keyboard shortcuts and signing out.
import { Keyboard, LogOut, Monitor, Moon, Sun } from 'lucide-react';
import type { Theme } from '@/ui/theme';
import type { Cmd, Section } from './layout';
import type { HoldingPage, PaletteEntry, PaletteIcon } from './sources';

export const asCmd =
    (section: Section) =>
    (entry: PaletteEntry): Cmd => ({ ...entry, section });

/** What pages handed the palette, each under its page's section. */
export function heldCommands(held: Partial<Record<HoldingPage, readonly PaletteEntry[]>>): Cmd[] {
    return (Object.entries(held) as [HoldingPage, readonly PaletteEntry[]][]).flatMap(([page, entries]) => entries.map(asCmd(page)));
}

/** What registered sources added: the places they go to, or (`actions`) the things they do in place. */
export function registeredEntries(registered: readonly PaletteEntry[], actions: boolean): PaletteEntry[] {
    return registered.filter((e) => !!e.action === actions);
}

// Appearance options surfaced as Account commands (mirrors the account menu's picker). The active one is marked.
const THEME_OPTIONS: { value: Theme; label: string; icon: PaletteIcon; keywords: string }[] = [
    { value: 'light', label: 'light', icon: Sun, keywords: 'bright day white appearance mode' },
    { value: 'dark', label: 'dark', icon: Moon, keywords: 'night black appearance mode' },
    { value: 'system', label: 'system', icon: Monitor, keywords: 'auto os default appearance mode' },
];

export function themeCommands(theme: Theme, setTheme: (theme: Theme) => void): Cmd[] {
    return THEME_OPTIONS.map((opt) => ({
        id: `account:theme:${opt.value}`,
        label: `Switch to ${opt.label} theme`,
        section: 'Account',
        icon: opt.icon,
        keywords: `theme appearance color scheme ${opt.keywords}`,
        // Mark the active choice; closes on select like every other command.
        meta: theme === opt.value ? 'Active' : undefined,
        run: () => setTheme(opt.value),
    }));
}

export function shortcutsCommand(show: () => void): Cmd {
    return { id: 'account:shortcuts', label: 'Open keyboard shortcuts', section: 'Account', icon: Keyboard, keywords: 'keys help hotkeys', keepOpen: true, run: show };
}

export function signOutCommand(signOut: () => void): Cmd {
    return { id: 'account:sign-out', label: 'Sign out', section: 'Account', icon: LogOut, keywords: 'log out logout exit', run: signOut };
}
