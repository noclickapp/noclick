// @vitest-environment happy-dom
// Your sections in Home's list, over the fake /v1 and the real platform client: one made from the Channels menu takes
// channels from their rows' menus, folds (still showing what's unread and what's open), and is kept on the server, so
// another device opens it as you left it; a frame from another device moves the list live; a save that loses to
// another device's is made again on what it kept; deleting a section puts its channels back in Channels; and the
// Channels list folds too, remembered the same way.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { workFixtureClient } from '../fixtures/client';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { WorkClientContext } from '../client';
import { fakeWork, sectionsKey, type FakeWork } from '../fixtures/workApi';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from '../Work';
import { MORE_AGENTS } from '@/screens/channels/slots';
import { fill } from '@/slots';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
// No agents from Automations in the pickers here (the hosted fill would ask the app's socket).
fill(MORE_AGENTS, null);
/** The account's own sections of the NoClick space, as the fake server keeps them. */
const KEY = sectionsKey(null, 'ws_noclick');
const SECTION_ID = '0f4c2b8e-7d1a-4c3e-9b5f-2a6d8e1c4b70';

beforeEach(() => localStorage.clear());
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

/** Work in the NoClick space's Home, on a laptop (#launch open) or a phone (the list): a fresh client, as another
 *  device would have. */
async function openHome(fake: FakeWork, { phone = false } = {}) {
    const client = workFixtureClient(fake.fetch);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: [`/dashboard?tab=work&space=ws_noclick${phone ? '' : '&channel=ch_launch'}`] });
    const work = (
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={fake.live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    render(
        phone ? (
            <PhoneBarSlotProvider slot={null} lead={null} setLeadTaken={() => undefined}>
                {work}
            </PhoneBarSlotProvider>
        ) : (
            work
        )
    );
    await screen.findByTestId('home-channels', {}, { timeout: 5000 });
    await waitFor(() => expect(fake.requests.some((r) => r.path === '/v1/channels/sections')).toBe(true));
}

const kept = (fake: FakeWork) => fake.sections.get(KEY) as { version: number; folded: string[]; sections: { id: string; name: string; folded: boolean; channel_ids: string[] }[] } | undefined;
const listOf = (testId: string) => screen.getByTestId(testId);
const rowsIn = (el: HTMLElement) => within(el).queryAllByRole('listitem').map((li) => li.getAttribute('data-channel'));

async function pick(trigger: HTMLElement, item: string) {
    fireEvent.keyDown(trigger, { key: 'Enter' });
    fireEvent.click(await screen.findByRole('menuitem', { name: item }));
    // The menu has closed before the next one opens: its items are never mistaken for the next's.
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
}

async function moveToSection(channel: string, section: string) {
    await pick(screen.getByRole('button', { name: `Move #${channel} to a section` }), section);
}

it('a section takes channels from their menus, folds to what’s unread and open, and opens so on another device', async () => {
    const fake = fakeWork();
    await openHome(fake);
    expect(rowsIn(listOf('home-channels'))).toEqual(['ch_launch', 'ch_incidents', 'ch_seo']);

    await pick(screen.getByRole('button', { name: 'Channels options' }), 'New section');
    const name = await screen.findByRole('textbox', { name: 'Section name' });
    fireEvent.change(name, { target: { value: '  Launch   week ' } });
    fireEvent.keyDown(name, { key: 'Enter' });
    await waitFor(() => expect(kept(fake)?.sections.map((s) => [s.name, s.channel_ids])).toEqual([['Launch week', []]]));

    for (const channel of ['seo', 'incidents', 'launch']) await moveToSection(channel, 'Launch week');
    await waitFor(() => expect(kept(fake)?.sections[0].channel_ids).toEqual(['ch_seo', 'ch_incidents', 'ch_launch']));
    expect(rowsIn(listOf('home-section'))).toEqual(['ch_seo', 'ch_incidents', 'ch_launch']);
    expect(rowsIn(listOf('home-channels'))).toEqual([]);

    // Folded, it keeps what's unread (#incidents) and what's open (#launch).
    fireEvent.click(screen.getByRole('button', { name: 'Fold Launch week' }));
    expect(rowsIn(listOf('home-section'))).toEqual(['ch_incidents', 'ch_launch']);
    await waitFor(() => expect(kept(fake)?.sections[0].folded).toBe(true));
    expect(screen.getByRole('button', { name: 'Unfold Launch week' }).getAttribute('aria-expanded')).toBe('false');

    // Another device opens Home as it was left: the section, its channels, folded.
    cleanup();
    await openHome(fake);
    await waitFor(() => expect(rowsIn(listOf('home-section'))).toEqual(['ch_incidents', 'ch_launch']));
    fireEvent.click(screen.getByRole('button', { name: 'Unfold Launch week' }));
    expect(rowsIn(listOf('home-section'))).toEqual(['ch_seo', 'ch_incidents', 'ch_launch']);
});

it('Channels folds to what’s unread and open, remembered on the server, and a frame from another device moves the list', async () => {
    const fake = fakeWork();
    await openHome(fake);
    fireEvent.click(screen.getByRole('button', { name: 'Fold Channels' }));
    expect(rowsIn(listOf('home-channels'))).toEqual(['ch_launch', 'ch_incidents']);
    await waitFor(() => expect(kept(fake)?.folded).toEqual(['channels']));

    // Another device made a section and put #seo in it: its frame moves this list at once.
    fake.sections.set(KEY, { ...kept(fake)!, version: 2, folded: [], sections: [{ id: SECTION_ID, name: 'Search', folded: false, channel_ids: ['ch_seo'] }] });
    fake.live.deliver('platform:channel', { kind: 'sections', channel_id: null, workspace_id: 'ws_noclick', message_id: null } as never);
    await waitFor(() => expect(rowsIn(listOf('home-section'))).toEqual(['ch_seo']));
    expect(rowsIn(listOf('home-channels'))).toEqual(['ch_launch', 'ch_incidents']);
    // Another space's frame isn't this list's.
    const reads = fake.requests.filter((r) => r.path === '/v1/channels/sections').length;
    fake.live.deliver('platform:channel', { kind: 'sections', channel_id: null, workspace_id: 'ws_wirefern', message_id: null } as never);
    await new Promise((r) => setTimeout(r, 20));
    expect(fake.requests.filter((r) => r.path === '/v1/channels/sections').length).toBe(reads);
});

it('a save that loses to another device’s is made again on what it kept, and a deleted section’s channels go back', async () => {
    const fake = fakeWork();
    await openHome(fake);
    // Another device saved a section this one hasn't heard of.
    fake.sections.set(KEY, { object: 'channel_sections', workspace_id: 'ws_noclick', version: 4, folded: [], updated_at: null, sections: [{ id: SECTION_ID, name: 'Search', folded: false, channel_ids: ['ch_seo'] }] });

    await pick(screen.getByRole('button', { name: 'Channels options' }), 'New section');
    const name = await screen.findByRole('textbox', { name: 'Section name' });
    fireEvent.change(name, { target: { value: 'Ops' } });
    fireEvent.keyDown(name, { key: 'Enter' });
    // The first save lost (409); made again on version 4, both sections are kept.
    await waitFor(() => expect(kept(fake)?.sections.map((s) => s.name)).toEqual(['Search', 'Ops']));
    expect(kept(fake)?.version).toBe(5);
    expect(fake.requests.filter((r) => r.method === 'PUT' && r.path === '/v1/channels/sections').map((r) => (r.body as { version: number }).version)).toEqual([0, 4]);
    await waitFor(() => expect(screen.getAllByTestId('home-section')).toHaveLength(2));

    await moveToSection('incidents', 'Ops');
    await waitFor(() => expect(kept(fake)?.sections[1].channel_ids).toEqual(['ch_incidents']));
    // Deleted, Ops's channel goes back to Channels; Search keeps its own.
    await pick(screen.getByRole('button', { name: 'Ops options' }), 'Delete section');
    await waitFor(() => expect(kept(fake)?.sections.map((s) => s.name)).toEqual(['Search']));
    expect(rowsIn(listOf('home-channels'))).toEqual(['ch_launch', 'ch_incidents']);
    expect(rowsIn(listOf('home-section'))).toEqual(['ch_seo']);
});

it('a section is renamed and reordered from its menu, and a starred channel moved into one leaves Starred', async () => {
    const fake = fakeWork();
    Object.assign(fake.channels.find((c) => c.id === 'ch_seo')!, { starred: true });
    fake.sections.set(KEY, {
        object: 'channel_sections',
        workspace_id: 'ws_noclick',
        version: 1,
        folded: [],
        updated_at: null,
        sections: [
            { id: SECTION_ID, name: 'Search', folded: false, channel_ids: [] },
            { id: '6a1e3d2c-5b4f-4e8a-9c7d-1f2e3a4b5c6d', name: 'Ops', folded: false, channel_ids: [] },
        ],
    });
    await openHome(fake);
    await waitFor(() => expect(screen.getAllByTestId('home-section')).toHaveLength(2));
    expect(rowsIn(listOf('starred-channels'))).toEqual(['ch_seo']);

    await pick(screen.getByRole('button', { name: 'Ops options' }), 'Move up');
    await waitFor(() => expect(kept(fake)?.sections.map((s) => s.name)).toEqual(['Ops', 'Search']));
    await pick(screen.getByRole('button', { name: 'Search options' }), 'Rename');
    const name = await screen.findByRole('textbox', { name: 'Section name' });
    fireEvent.change(name, { target: { value: 'Search and guides' } });
    fireEvent.keyDown(name, { key: 'Enter' });
    await waitFor(() => expect(kept(fake)?.sections.map((s) => s.name)).toEqual(['Ops', 'Search and guides']));

    await moveToSection('seo', 'Search and guides');
    await waitFor(() => expect(fake.channels.find((c) => c.id === 'ch_seo')?.starred).toBe(false));
    await waitFor(() => expect(screen.queryByTestId('starred-channels')).toBeNull());
    expect(rowsIn(screen.getAllByTestId('home-section')[1])).toEqual(['ch_seo']);
});

/** The layout with two empty sections the server keeps for the account, as another device left it. */
const twoSections = (fake: FakeWork) =>
    fake.sections.set(KEY, {
        object: 'channel_sections',
        workspace_id: 'ws_noclick',
        version: 1,
        folded: [],
        updated_at: null,
        sections: [
            { id: SECTION_ID, name: 'Search', folded: false, channel_ids: ['ch_launch'] },
            { id: '6a1e3d2c-5b4f-4e8a-9c7d-1f2e3a4b5c6d', name: 'Ops', folded: false, channel_ids: [] },
        ],
    });

/** A drag as the browser sends it: its data travels in `dataTransfer`. */
function dragFrom(from: Element) {
    const data = new Map<string, string>();
    const dataTransfer = { setData: (k: string, v: string) => void data.set(k, v), getData: (k: string) => data.get(k) ?? '', effectAllowed: '', dropEffect: '', types: [] };
    fireEvent.dragStart(from, { dataTransfer });
    return {
        drop(on: Element, { below = false } = {}) {
            // Above or below the middle of what it's over (the test's boxes are 0 tall at 0).
            fireEvent.dragOver(on, { dataTransfer, clientY: below ? 1 : 0 });
            fireEvent.drop(on, { dataTransfer, clientY: below ? 1 : 0 });
            fireEvent.dragEnd(from, { dataTransfer });
        },
    };
}

it('a channel is dragged into a section, before the row it lands on, and a section is dragged above another', async () => {
    const fake = fakeWork();
    twoSections(fake);
    await openHome(fake);
    await waitFor(() => expect(screen.getAllByTestId('home-section')).toHaveLength(2));
    const row = (id: string) => document.querySelector(`li[data-channel="${id}"]`)!;

    // #seo onto #launch's upper half: into Search, before it.
    dragFrom(row('ch_seo')).drop(row('ch_launch'));
    await waitFor(() => expect(kept(fake)?.sections[0].channel_ids).toEqual(['ch_seo', 'ch_launch']));
    // #incidents onto the empty Ops section's header.
    dragFrom(row('ch_incidents')).drop(screen.getByRole('button', { name: 'Fold Ops' }));
    await waitFor(() => expect(kept(fake)?.sections[1].channel_ids).toEqual(['ch_incidents']));
    // #launch back onto Channels.
    dragFrom(row('ch_launch')).drop(screen.getByRole('button', { name: 'Fold Channels' }));
    await waitFor(() => expect(kept(fake)?.sections[0].channel_ids).toEqual(['ch_seo']));
    expect(rowsIn(listOf('home-channels'))).toEqual(['ch_launch']);

    // Ops, dragged by its name onto Search's upper half, goes above it.
    dragFrom(screen.getByText('Ops')).drop(screen.getByText('Search'));
    await waitFor(() => expect(kept(fake)?.sections.map((s) => s.name)).toEqual(['Ops', 'Search']));
    // A section dragged onto a built-in list goes nowhere.
    const version = kept(fake)?.version;
    dragFrom(screen.getByText('Ops')).drop(screen.getByRole('button', { name: 'Fold Channels' }));
    await new Promise((r) => setTimeout(r, 30));
    expect(kept(fake)?.version).toBe(version);
});

it('on a phone, holding a channel opens its Move menu, without opening the channel', async () => {
    const fake = fakeWork();
    twoSections(fake);
    await openHome(fake, { phone: true });
    await waitFor(() => expect(screen.getAllByTestId('home-section')).toHaveLength(2));
    const row = document.querySelector('li[data-channel="ch_seo"]')!;
    // The rows carry no menu of their own to tap on a phone; the section headers keep theirs.
    expect(screen.getByRole('button', { name: 'Move #seo to a section' }).className).toContain('pointer-events-none');
    expect(screen.getByRole('button', { name: 'Ops options' }).className).not.toContain('opacity-0');

    fireEvent.pointerDown(row, { pointerType: 'touch', clientX: 20, clientY: 20 });
    await screen.findByRole('menuitem', { name: 'Ops' }, { timeout: 2000 });
    fireEvent.pointerUp(row, { pointerType: 'touch' });
    fireEvent.click(row.querySelector('button')!);
    expect(screen.queryByTestId('channel-pane')).toBeNull();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ops' }));
    await waitFor(() => expect(kept(fake)?.sections[1].channel_ids).toEqual(['ch_seo']));

    // Held, a channel goes into a section made for it there and then.
    fireEvent.pointerDown(document.querySelector('li[data-channel="ch_launch"]')!, { pointerType: 'touch', clientX: 20, clientY: 20 });
    fireEvent.click(await screen.findByRole('menuitem', { name: 'New section' }, { timeout: 2000 }));
    const name = await screen.findByRole('textbox', { name: 'Section name' });
    fireEvent.change(name, { target: { value: 'Shipping' } });
    fireEvent.keyDown(name, { key: 'Enter' });
    await waitFor(() => expect(kept(fake)?.sections.map((s) => [s.name, s.channel_ids])).toEqual([['Search', []], ['Ops', ['ch_seo']], ['Shipping', ['ch_launch']]]));

    // A finger that moves is scrolling: no menu.
    fireEvent.pointerDown(document.querySelector('li[data-channel="ch_incidents"]')!, { pointerType: 'touch', clientX: 20, clientY: 20 });
    fireEvent.pointerMove(document.querySelector('li[data-channel="ch_incidents"]')!, { pointerType: 'touch', clientX: 20, clientY: 60 });
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.queryByRole('menu')).toBeNull();
});
