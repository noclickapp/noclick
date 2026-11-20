// Opening the command palette from anywhere: the sidebar's search, a shortcut, a page's Find. The palette listens for
// one window event, so whatever opens it needs no handle on it.

/** A section the palette can be opened narrowed to ("Open automation…"). */
export type PaletteScope = 'Workflows' | 'Credentials';

export const OPEN_COMMAND_PALETTE_EVENT = 'noclick:open-command-palette';

export interface OpenCommandPaletteDetail {
    /** Omitted/undefined opens the full palette; set restricts it to one scope. */
    scope?: PaletteScope;
    /** Which page to land on — 'root' (default) or the keyboard-shortcuts list. */
    page?: 'root' | 'shortcuts';
}

/** Open the command palette, optionally pre-scoped to a category. */
export function openCommandPalette(scope?: PaletteScope): void {
    window.dispatchEvent(new CustomEvent<OpenCommandPaletteDetail>(OPEN_COMMAND_PALETTE_EVENT, { detail: { scope } }));
}

/** Open the command palette straight to the keyboard-shortcuts list. */
export function openKeyboardShortcuts(): void {
    window.dispatchEvent(new CustomEvent<OpenCommandPaletteDetail>(OPEN_COMMAND_PALETTE_EVENT, { detail: { page: 'shortcuts' } }));
}
