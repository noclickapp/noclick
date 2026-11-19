// @vitest-environment happy-dom
// Every icon-only button in Work's rails (spaces, views), its lists (Home with a section, Agents, DMs, Resources) and a
// channel's box names itself with the app's tooltip, shown on keyboard focus or on hover: an icon alone says nothing to
// someone who hasn't learnt it. None leans on the browser's `title`, and none shows a keyboard shortcut.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { workFixtureClient } from './fixtures/client';
import { WorkClientContext } from './client';
import { fakeWork, sectionsKey } from './fixtures/workApi';
import { LIST_OPENS } from './listRail';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';
import { MORE_AGENTS } from '@/screens/channels/slots';
import { fill } from '@/slots';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
// No agents from Automations in the pickers here (the hosted fill would ask the app's socket).
fill(MORE_AGENTS, null);
/** Keys a tooltip never shows (Rowan's rule: shortcuts work, they're never printed). */
const SHORTCUT = /[⌘⇧⌥⌃]|\b(ctrl|cmd|shift|alt)\s*\+/i;

beforeEach(() => localStorage.clear());
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

function openWork() {
    const measure = HTMLElement.prototype.getBoundingClientRect;
    // A laptop's pane, wide enough for every list to stay docked.
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
        return this.previousElementSibling?.matches('[data-testid="work-list"]') ? DOMRect.fromRect({ width: LIST_OPENS + 400, height: 800 }) : measure.call(this);
    });
    const fake = fakeWork();
    fake.sections.set(sectionsKey(null, 'ws_noclick'), {
        object: 'channel_sections',
        workspace_id: 'ws_noclick',
        version: 1,
        folded: [],
        updated_at: null,
        sections: [{ id: '0f4c2b8e-7d1a-4c3e-9b5f-2a6d8e1c4b70', name: 'Launch week', folded: false, channel_ids: ['ch_launch'] }],
    });
    const client = workFixtureClient(fake.fetch);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: ['/dashboard?tab=work&space=ws_noclick&channel=ch_launch'] });
    render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={fake.live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
}

/** A button that shows only an icon: no text of its own (a count badge's number doesn't name it). */
const iconOnly = (b: HTMLElement) => !(b.textContent ?? '').replace(/\d+/g, '').trim();

const tipText = () =>
    screen
        .queryAllByRole('tooltip')
        .map((t) => t.textContent?.trim() ?? '')
        .filter(Boolean);

/** The tooltip `button` shows on keyboard focus, or else on a resting pointer; null when it shows none. */
async function tipOf(button: HTMLElement): Promise<string | null> {
    act(() => button.focus());
    fireEvent.focus(button);
    let said = tipText();
    if (!said.length) {
        fireEvent.pointerEnter(button, { pointerType: 'mouse' });
        fireEvent.pointerMove(button, { pointerType: 'mouse' });
        await waitFor(() => expect(tipText().length).toBeGreaterThan(0), { timeout: 800 }).catch(() => undefined);
        said = tipText();
    }
    fireEvent.pointerLeave(button, { pointerType: 'mouse' });
    fireEvent.keyDown(button, { key: 'Escape' });
    act(() => button.blur());
    fireEvent.blur(button);
    await waitFor(() => expect(tipText()).toEqual([]), { timeout: 1500 });
    return said.length ? said.join(' / ') : null;
}

/** Each icon-only button in `places` and what its tooltip says (null: nothing). */
async function audit(places: HTMLElement[]): Promise<Record<string, string | null>> {
    const found: Record<string, string | null> = {};
    for (const place of places) {
        for (const button of within(place).queryAllByRole('button').filter(iconOnly)) {
            const name = button.getAttribute('aria-label') ?? button.outerHTML.slice(0, 80);
            expect(button.hasAttribute('title'), `${name} leans on title=`).toBe(false);
            found[name] = await tipOf(button);
        }
    }
    return found;
}

const rails = () => [screen.getByRole('navigation', { name: 'Spaces' }), screen.getByRole('navigation', { name: 'Views' })];
const theList = () => screen.getByRole('navigation', { name: 'The list' });

async function show(view: 'Home' | 'Agents' | 'DMs' | 'Resources', testId: string) {
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Views' })).getByRole('button', { name: new RegExp(`${view}$`) }));
    await screen.findByTestId(testId, {}, { timeout: 5000 });
}

it('every icon-only button in Work’s rails, lists and a channel’s box names itself with a tooltip', async () => {
    openWork();
    await screen.findByTestId('home-section', {}, { timeout: 5000 });
    const composer = await screen.findByTestId('channel-composer', {}, { timeout: 5000 });
    const found = await audit([...rails(), theList(), composer]);
    for (const view of [
        ['Agents', 'agents-list'],
        ['DMs', 'dms-list'],
        ['Resources', 'space-resources-nav'],
    ] as const) {
        await show(view[0], view[1]);
        Object.assign(found, await audit([theList()]));
    }
    // An agent's box: from its text up to the part that holds its Send.
    await show('Agents', 'agents-list');
    fireEvent.click(within(theList()).getByRole('button', { name: /^Support/ }));
    let box: HTMLElement = await screen.findByRole('textbox', { name: 'Message Support' }, { timeout: 5000 });
    while (!box.querySelector('[data-primary]') && box.parentElement) box = box.parentElement;
    Object.assign(found, await audit([box]));

    if (process.env.PRINT_TIPS) console.log(JSON.stringify(found, null, 1));
    const missing = Object.entries(found).filter(([, tip]) => !tip);
    expect(missing, `no tooltip on: ${missing.map(([n]) => n).join(', ')}`).toEqual([]);
    const shortcuts = Object.entries(found).filter(([, tip]) => SHORTCUT.test(tip ?? ''));
    expect(shortcuts).toEqual([]);
    // The ones Rowan named, as they read.
    expect(found).toMatchObject({
        'New space': 'New space',
        'Create a channel': 'Create a channel',
        'Fold Launch week': 'Fold',
        'Fold Channels': 'Fold',
        'Launch week options': 'Section options',
        'Move #launch to a section': 'Move to section',
        'Attach files': 'Attach files',
        'Emoji': 'Emoji',
        'Mention someone': 'Mention someone',
    });
});
