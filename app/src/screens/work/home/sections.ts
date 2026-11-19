// Your own sections of Home's channels, as Slack's sidebar groups them: the model, as pure changes to a layout and how
// a layout groups the space's channels. The layout is kept for you on the server (useChannelSections), one per space.
//
// A channel sits in one section at most; one in none is in the built-in Channels list. Starred wins: a starred channel
// shows under Starred whichever section holds it, so moving one into a section takes its star off (HomeList). Each
// section and each built-in list folds on its own; folded, it still shows the channels with something for you (unread,
// or an @-mention where it's muted) and the one that's open, as Slack keeps them.
import type { Channel } from '@/screens/channels/types';

export type BuiltInList = 'starred' | 'channels';
export const BUILT_IN_LISTS: readonly BuiltInList[] = ['starred', 'channels'];

export interface Section {
    id: string;
    name: string;
    folded: boolean;
    channelIds: string[];
}

export interface Layout {
    /** The version it was read at (0: none saved yet), which a save names. */
    version: number;
    sections: Section[];
    folded: BuiltInList[];
}

export const EMPTY_LAYOUT: Layout = { version: 0, sections: [], folded: [] };
export const MAX_SECTION_NAME = 80;

/** A section's name as it's kept: one line, spaces collapsed, at most MAX_SECTION_NAME. */
export const cleanSectionName = (name: string) => name.split(/\s+/).filter(Boolean).join(' ').slice(0, MAX_SECTION_NAME);

/** Where a channel can go: a section's id, or null for the built-in Channels list. */
export type Destination = string | null;

/** A change to a layout; the version stays as read, which its save names. */
export type LayoutChange = (layout: Layout) => Layout;

const without = (layout: Layout, channelId: string): Section[] => layout.sections.map((s) => (s.channelIds.includes(channelId) ? { ...s, channelIds: s.channelIds.filter((id) => id !== channelId) } : s));

/** A new section called `name`, after the others (or at `index`), empty and open. */
export const addSection =
    (id: string, name: string, index?: number): LayoutChange =>
    (layout) => {
        const sections = [...layout.sections];
        sections.splice(index ?? sections.length, 0, { id, name: cleanSectionName(name), folded: false, channelIds: [] });
        return { ...layout, sections };
    };

export const renameSection =
    (id: string, name: string): LayoutChange =>
    (layout) => ({ ...layout, sections: layout.sections.map((s) => (s.id === id ? { ...s, name: cleanSectionName(name) || s.name } : s)) });

/** The section goes; its channels go back to Channels, simply by being in no section. */
export const removeSection =
    (id: string): LayoutChange =>
    (layout) => ({ ...layout, sections: layout.sections.filter((s) => s.id !== id) });

/** A section put back where it was (an undone delete), its channels with it unless they've moved since. */
export const restoreSection =
    (section: Section, index: number): LayoutChange =>
    (layout) => {
        if (layout.sections.some((s) => s.id === section.id)) return layout;
        const elsewhere = new Set(layout.sections.flatMap((s) => s.channelIds));
        const sections = [...layout.sections];
        sections.splice(Math.min(index, sections.length), 0, { ...section, channelIds: section.channelIds.filter((id) => !elsewhere.has(id)) });
        return { ...layout, sections };
    };

/** The channel into section `to` (null: back to Channels), at `index` among its channels (the end by default). */
export const moveChannel =
    (channelId: string, to: Destination, index?: number): LayoutChange =>
    (layout) => {
        const sections = without(layout, channelId);
        if (to === null || !sections.some((s) => s.id === to)) return { ...layout, sections };
        return {
            ...layout,
            sections: sections.map((s) => {
                if (s.id !== to) return s;
                const channelIds = [...s.channelIds];
                channelIds.splice(Math.max(0, Math.min(index ?? channelIds.length, channelIds.length)), 0, channelId);
                return { ...s, channelIds };
            }),
        };
    };

/** The section to `index` among the sections. */
export const moveSection =
    (id: string, index: number): LayoutChange =>
    (layout) => {
        const from = layout.sections.findIndex((s) => s.id === id);
        if (from < 0) return layout;
        const sections = [...layout.sections];
        const [moved] = sections.splice(from, 1);
        sections.splice(Math.max(0, Math.min(index, sections.length)), 0, moved);
        return { ...layout, sections };
    };

const isBuiltIn = (key: string): key is BuiltInList => (BUILT_IN_LISTS as readonly string[]).includes(key);

/** Whether a section (by id) or a built-in list is folded. */
export const isFolded = (layout: Layout, key: string) => (isBuiltIn(key) ? layout.folded.includes(key) : (layout.sections.find((s) => s.id === key)?.folded ?? false));

/** Fold a section (by id) or a built-in list, or open it. */
export const setFolded =
    (key: string, folded: boolean): LayoutChange =>
    (layout) => {
        if (isBuiltIn(key)) return { ...layout, folded: BUILT_IN_LISTS.filter((k) => (k === key ? folded : layout.folded.includes(k))) };
        return { ...layout, sections: layout.sections.map((s) => (s.id === key ? { ...s, folded } : s)) };
    };

/** The section holding a channel, or null (Channels). */
export const sectionOf = (layout: Layout, channelId: string): Section | null => layout.sections.find((s) => s.channelIds.includes(channelId)) ?? null;

export interface Grouped {
    starred: Channel[];
    sections: { section: Section; channels: Channel[] }[];
    /** Channels: in no section and not starred. */
    rest: Channel[];
}

/** The space's channels under the layout: Starred, then each section in order (its channels as it orders them), then
 *  Channels. Open ones come before closed ones in each, each part otherwise as given. A section's channel the space
 *  doesn't hold (another space's, or gone) isn't shown and stays in the layout. */
export function groupChannels(channels: Channel[], layout: Layout): Grouped {
    const openFirst = (list: Channel[]) => [...list.filter((c) => c.status !== 'closed'), ...list.filter((c) => c.status === 'closed')];
    const byId = new Map(channels.map((c) => [c.id, c]));
    const placed = new Set<string>();
    const sections = layout.sections.map((section) => {
        const held = section.channelIds.flatMap((id) => {
            const channel = byId.get(id);
            if (!channel || placed.has(id)) return [];
            placed.add(id);
            return channel.starred ? [] : [channel];
        });
        return { section, channels: openFirst(held) };
    });
    const ordered = openFirst(channels);
    return { starred: ordered.filter((c) => c.starred), sections, rest: ordered.filter((c) => !c.starred && !placed.has(c.id)) };
}

/** What a channel holds for you: unread messages (where it isn't muted) or an @-mention of you. */
export const hasNews = (c: Channel) => c.status !== 'closed' && ((c.mentions ?? 0) > 0 || (!c.muted && c.unread > 0));

/** A folded list's channels that still show: what has news for you, and the one that's open. */
export const shownFolded = (channels: Channel[], openId: string | null) => channels.filter((c) => c.id === openId || hasNews(c));
