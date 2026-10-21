// What the command palette is handed from outside it: places a deployment adds, through a registered source, and the
// things a page already holds (its resources, its channels), so the palette can jump to them without reading them
// itself.
import { useSyncExternalStore, type ComponentType } from 'react';
import type { Named } from '~/lib/fuzzyRank';

export type PaletteIcon = ComponentType<{ className?: string }>;

/** One row the palette can run. */
export interface PaletteEntry extends Named {
    /** Stable across sessions: the palette remembers what was used by it. */
    id: string;
    icon: PaletteIcon;
    /** A brand icon's colour (Tailwind class or hex), for a row that wears an app's logo. */
    iconColor?: string;
    /** Listed before anything is typed. */
    browse?: boolean;
    /** Something done in place, listed with the account's commands (the theme, sign-out), rather than a place to go. */
    action?: boolean;
    run: () => void;
}

export interface PaletteSourceProps {
    onEntries: (entries: readonly PaletteEntry[]) => void;
}

/** Adds entries to the palette: a component, rendered beside it, that reports them and reports again when they change.
 *  Registered lazily, so its code loads with the palette and never on a page without one. */
export type PaletteSource = ComponentType<PaletteSourceProps>;

const sources: PaletteSource[] = [];

export function registerPaletteSource(source: PaletteSource): void {
    sources.push(source);
}

export function paletteSources(): readonly PaletteSource[] {
    return sources;
}

/** The pages that hand the palette what they hold; each shows as a section of its own. */
export type HoldingPage = 'Resources' | 'Channels';

let held: Partial<Record<HoldingPage, readonly PaletteEntry[]>> = {};
const listeners = new Set<() => void>();

function changed(next: typeof held) {
    held = next;
    listeners.forEach((listener) => listener());
}

/** A page hands the palette what it holds, replacing what it handed before. */
export function rememberPaletteEntries(page: HoldingPage, entries: readonly PaletteEntry[]): void {
    changed({ ...held, [page]: entries });
}

/** Drops everything pages handed over (another workspace holds other things). */
export function forgetPaletteEntries(): void {
    if (Object.keys(held).length) changed({});
}

function subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

/** What pages have handed the palette this session, by page. */
export function useRememberedPaletteEntries(): Partial<Record<HoldingPage, readonly PaletteEntry[]>> {
    return useSyncExternalStore(
        subscribe,
        () => held,
        () => held
    );
}
