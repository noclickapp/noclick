// The section model Home's list is drawn from: making, naming, moving channels in and out, deleting (its channels go
// back to Channels), reordering and folding sections, and how a layout groups a space's channels.
import { describe, expect, it } from 'vitest';
import type { Channel } from '@/screens/channels/types';
import {
    addSection,
    cleanSectionName,
    EMPTY_LAYOUT,
    groupChannels,
    isFolded,
    moveChannel,
    moveSection,
    removeSection,
    renameSection,
    restoreSection,
    sectionOf,
    setFolded,
    shownFolded,
    type Layout,
    type LayoutChange,
} from './sections';

const channel = (id: string, fields: Partial<Channel> = {}): Channel =>
    ({ id, name: id, kind: 'channel', status: 'open', unread: 0, mentions: 0, starred: false, muted: false, members: [], createdAt: '2026-11-14T10:00:00Z', ...fields }) as Channel;

const apply = (...changes: LayoutChange[]): Layout => changes.reduce((l, c) => c(l), EMPTY_LAYOUT);
const names = (layout: Layout) => layout.sections.map((s) => `${s.name}:${s.channelIds.join(',')}`);

describe('sections', () => {
    it('makes a section, empty and open, after the others or where asked, its name tidied', () => {
        const layout = apply(addSection('a', 'Launch'), addSection('b', '  Customer \n calls  '), addSection('c', 'First', 0));
        expect(names(layout)).toEqual(['First:', 'Launch:', 'Customer calls:']);
        expect(layout.sections.every((s) => !s.folded)).toBe(true);
        expect(cleanSectionName('x'.repeat(200))).toHaveLength(80);
        // The version stays as read: the save names it.
        expect(layout.version).toBe(0);
    });

    it('renames a section, keeping the old name when the new one is blank', () => {
        const layout = apply(addSection('a', 'Launch'), renameSection('a', 'Launch plans'), renameSection('a', '   '));
        expect(names(layout)).toEqual(['Launch plans:']);
    });

    it('moves a channel into one section at most, in order, and back to Channels', () => {
        let layout = apply(addSection('a', 'Launch'), addSection('b', 'Ops'), moveChannel('c1', 'a'), moveChannel('c2', 'a'), moveChannel('c3', 'a', 0));
        expect(names(layout)).toEqual(['Launch:c3,c1,c2', 'Ops:']);
        // Into another section, it leaves the first.
        layout = moveChannel('c1', 'b')(layout);
        expect(names(layout)).toEqual(['Launch:c3,c2', 'Ops:c1']);
        expect(sectionOf(layout, 'c1')?.id).toBe('b');
        // Reordered within its own section.
        layout = moveChannel('c2', 'a', 0)(layout);
        expect(names(layout)).toEqual(['Launch:c2,c3', 'Ops:c1']);
        // Back to Channels: in no section.
        layout = moveChannel('c2', null)(layout);
        expect(names(layout)).toEqual(['Launch:c3', 'Ops:c1']);
        expect(sectionOf(layout, 'c2')).toBeNull();
        // A section that isn't there takes nothing: the channel goes back to Channels.
        expect(names(moveChannel('c3', 'gone')(layout))).toEqual(['Launch:', 'Ops:c1']);
    });

    it('deletes a section, its channels going back to Channels, and an undo puts it back as it was', () => {
        const layout = apply(addSection('a', 'Launch'), addSection('b', 'Ops'), moveChannel('c1', 'a'), moveChannel('c2', 'a'));
        const launch = layout.sections[0];
        const gone = removeSection('a')(layout);
        expect(names(gone)).toEqual(['Ops:']);
        const grouped = groupChannels([channel('c1'), channel('c2'), channel('c3')], gone);
        expect(grouped.rest.map((c) => c.id)).toEqual(['c1', 'c2', 'c3']);
        // Undone, it's back in its place; a channel moved meanwhile stays where it went.
        const back = restoreSection(launch, 0)(moveChannel('c2', 'b')(gone));
        expect(names(back)).toEqual(['Launch:c1', 'Ops:c2']);
        expect(restoreSection(launch, 0)(back)).toBe(back);
    });

    it('reorders sections', () => {
        const layout = apply(addSection('a', 'A'), addSection('b', 'B'), addSection('c', 'C'));
        expect(names(moveSection('a', 2)(layout))).toEqual(['B:', 'C:', 'A:']);
        expect(names(moveSection('c', 0)(layout))).toEqual(['C:', 'A:', 'B:']);
        expect(names(moveSection('b', 99)(layout))).toEqual(['A:', 'C:', 'B:']);
        expect(moveSection('gone', 0)(layout)).toBe(layout);
    });

    it('folds each section and built-in list on its own, and keeps it through other changes', () => {
        let layout = apply(addSection('a', 'Launch'), addSection('b', 'Ops'), setFolded('a', true), setFolded('channels', true));
        expect([isFolded(layout, 'a'), isFolded(layout, 'b'), isFolded(layout, 'channels'), isFolded(layout, 'starred')]).toEqual([true, false, true, false]);
        layout = apply(...[addSection('a', 'Launch'), addSection('b', 'Ops'), setFolded('a', true), setFolded('channels', true), setFolded('starred', true), setFolded('channels', false)]);
        // The built-in lists keep one order, as the server keeps them.
        expect(layout.folded).toEqual(['starred']);
        // Renamed, moved and filled, a folded section stays folded.
        layout = moveSection('a', 1)(renameSection('a', 'Launch plans')(moveChannel('c1', 'a')(layout)));
        expect(layout.sections.map((s) => [s.name, s.folded])).toEqual([
            ['Ops', false],
            ['Launch plans', true],
        ]);
    });

    it('groups channels: starred first wherever they sit, each section in its order, the rest in Channels', () => {
        const layout = apply(addSection('a', 'Launch'), moveChannel('c3', 'a'), moveChannel('c1', 'a'), moveChannel('starry', 'a'), moveChannel('elsewhere', 'a'));
        const grouped = groupChannels([channel('c1'), channel('c2'), channel('c3', { status: 'closed' }), channel('c4'), channel('starry', { starred: true })], layout);
        expect(grouped.starred.map((c) => c.id)).toEqual(['starry']);
        // Open before closed; a channel the space doesn't hold isn't shown (and stays in the layout).
        expect(grouped.sections.map((g) => [g.section.name, g.channels.map((c) => c.id)])).toEqual([['Launch', ['c1', 'c3']]]);
        expect(grouped.rest.map((c) => c.id)).toEqual(['c2', 'c4']);
        expect(layout.sections[0].channelIds).toContain('elsewhere');
    });

    it('folded, a list still shows what has something for you and what’s open', () => {
        const list = [channel('quiet'), channel('unread', { unread: 2 }), channel('muted', { muted: true, unread: 5 }), channel('mentioned', { muted: true, unread: 1, mentions: 1 }), channel('open'), channel('closed', { status: 'closed', unread: 3 })];
        expect(shownFolded(list, 'open').map((c) => c.id)).toEqual(['unread', 'mentioned', 'open']);
    });
});
