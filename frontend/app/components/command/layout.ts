// How the command palette lays its rows out: before anything is typed, the latest places someone went to, then each
// section's opening rows; with a query, each section's matches best first, the sections in order of their best.
import { scoreNamed } from '~/lib/fuzzyRank';
import type { PaletteScope } from '~/lib/shortcuts';
import { frecency, type Use } from './history';
import type { HoldingPage, PaletteEntry } from './sources';

// 'Workflows' and 'Credentials' double as the scopes "O W" and "O C" open.
export type Section = 'Actions' | 'Open' | 'Go to' | 'Workflows' | 'Credentials' | HoldingPage | 'Setup' | 'Account';

export interface Cmd extends Omit<PaletteEntry, 'action'> {
    section: Section;
    /** Node types for the integration-logo stack (workflow rows). */
    nodeTypes?: string[];
    /** Trailing metadata line (e.g. "5 nodes · 2d ago" for workflow rows). */
    meta?: string;
    /** When true the palette stays open after running (e.g. opening a sub-page). */
    keepOpen?: boolean;
}

// The empty palette's order: what to make first, then where to go.
export const SECTION_ORDER: Section[] = ['Actions', 'Open', 'Go to', 'Workflows', 'Credentials', 'Resources', 'Channels', 'Setup', 'Account'];
// With a query, sections are ordered by their best match, and a place wins a tie with a command.
const QUERY_ORDER: Section[] = ['Go to', 'Workflows', 'Credentials', 'Resources', 'Channels', 'Actions', 'Open', 'Setup', 'Account'];
/** Rows that take you somewhere; the latest of these are offered first. */
export const PLACES = new Set<Section>(['Go to', 'Workflows', 'Credentials', 'Resources', 'Channels']);
// How many of a section a query shows; a scope shows more.
const QUERY_LIMIT: Partial<Record<Section, number>> = { 'Go to': 10, Workflows: 6, Credentials: 5, Resources: 5, Channels: 5 };
const SCOPE_LIMIT = 50;
const RECENT_LIMIT = 5;
const BROWSE_WORKFLOWS = 3;

/** Before anything is typed: the pages (and whatever else is marked to browse), a few automations, and every command;
 *  accounts, resources and channels wait to be searched for. */
function opening(section: Section, items: Cmd[]): Cmd[] {
    if (section === 'Go to') return items.filter((c) => c.browse);
    if (section === 'Workflows') return items.slice(0, BROWSE_WORKFLOWS);
    if (section === 'Credentials' || section === 'Resources' || section === 'Channels') return [];
    return items;
}

export function layoutCommands(
    commands: readonly Cmd[],
    query: string,
    scope: PaletteScope | null,
    uses: Record<string, Use>,
    now = Date.now()
): { title: Section | 'Recent'; items: Cmd[] }[] {
    const q = query.trim();
    if (!q && scope) return [{ title: scope, items: commands.filter((c) => c.section === scope).slice(0, SCOPE_LIMIT) }].filter((s) => s.items.length > 0);
    if (!q) {
        const recent = commands
            .filter((c) => PLACES.has(c.section) && uses[c.id])
            .sort((a, b) => uses[b.id].at - uses[a.id].at)
            .slice(0, RECENT_LIMIT);
        const shown = new Set(recent.map((c) => c.id));
        const sections = SECTION_ORDER.map((section) => ({
            title: section,
            items: opening(
                section,
                commands.filter((c) => c.section === section && !shown.has(c.id))
            ),
        }));
        return [{ title: 'Recent' as const, items: recent }, ...sections].filter((s) => s.items.length > 0);
    }
    // Ties go to what's run more and lately, then to the catalogue's own order.
    return (scope ? [scope] : QUERY_ORDER)
        .map((section, order) => {
            const scored = commands
                .filter((c) => c.section === section)
                .flatMap((c, index) => {
                    const score = scoreNamed(q, c);
                    return score === null ? [] : [{ c, index, score, strength: frecency(uses[c.id], now) }];
                })
                .sort((a, b) => a.score - b.score || b.strength - a.strength || a.index - b.index);
            const limit = scope ? SCOPE_LIMIT : (QUERY_LIMIT[section] ?? Infinity);
            return { title: section, order, items: scored.slice(0, limit).map((x) => x.c), best: scored[0]?.score ?? Infinity };
        })
        .filter((s) => s.items.length > 0)
        .sort((a, b) => a.best - b.best || a.order - b.order)
        .map(({ title, items }) => ({ title, items }));
}
