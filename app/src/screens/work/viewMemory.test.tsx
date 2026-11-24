// @vitest-environment happy-dom
// Each of Work's views reopens what was last open in it, per space, over the fake /v1: an agent picked in Agents (its
// profile too, its one session needing no name) is there again after a visit to Home, as is the DM you last had open in DMs, not
// the newest. Something gone since (a deleted agent) opens the view with nothing open; what the URL names (an agent
// whose profile is beside) wins over what was remembered; and a phone shows each view's list. With nothing open, a
// view's pane shows what's there to open, or the way to make or start one, never a blank pane.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { WorkClientContext } from './client';
import { fakeWork, type FakeWork } from './fixtures/workApi';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
const VIEWS_KEY = 'nc-work-channels';

beforeEach(() => localStorage.clear());
afterEach(cleanup);

function showWork(fake: FakeWork, url: string, wrap: (page: ReactNode) => ReactNode = (page) => page) {
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: [url] });
    render(
        <WorkClientContext.Provider value={fake.client}>
            <WorkLiveContext.Provider value={fake.live}>
                {wrap(<RouterProvider router={router} />)}
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    const param = (name: string) => new URLSearchParams(router.state.location.search).get(name);
    return { param, at: (...names: string[]) => names.map(param) };
}

/** A view on the views' rail (the phone's bar). */
function view(name: 'Home' | 'Agents' | 'DMs' | 'Resources') {
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Views' })).getByRole('button', { name: new RegExp(`${name}$`) }));
}

async function agentRow(agentId: string): Promise<HTMLButtonElement> {
    return waitFor(() => {
        const row = document.querySelector<HTMLButtonElement>(`li[data-agent="${agentId}"] > button`);
        expect(row).toBeTruthy();
        return row!;
    });
}

/** A DM with Sam in the NoClick space, newer than Priya's. */
function withSam(fake: FakeWork) {
    const at = new Date(Date.now() - 5 * 60_000).toISOString();
    const sam = { type: 'user', id: 'usr_sam', name: 'Sam Rivera' };
    fake.channels.push({
        object: 'channel',
        id: 'dm_sam',
        name: 'sam-rivera',
        topic: '',
        mode: 'all',
        status: 'open',
        halt_reason: null,
        unread_count: 0,
        user_id: null,
        workspace_id: 'ws_noclick',
        kind: 'dm',
        members: [{ object: 'channel_member', id: 'mem_usr_sam', type: 'user', user_id: 'usr_sam', name: 'Sam Rivera', busy: false }],
        last_message: { id: 's1', text: 'Shipped the fix.', author: sam, created_at: at },
        created_at: at,
    });
    fake.messages.set('dm_sam', []);
}

it('Agents reopens the agent you picked after a visit to Home', async () => {
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=home&show=agents');
    fireEvent.click(await agentRow('agt_growth'));
    await waitFor(() => expect(work.param('agent')).toBe('agt_growth'));
    expect(await screen.findByTestId('agent-conversation')).toBeTruthy();

    view('Home');
    await waitFor(() => expect(work.param('show')).toBeNull());
    expect(work.param('agent')).toBeNull();

    view('Agents');
    await waitFor(() => expect(work.at('show', 'agent')).toEqual(['agents', 'agt_growth']));
    expect(await screen.findByTestId('agent-conversation')).toBeTruthy();
    expect((await agentRow('agt_growth')).getAttribute('aria-current')).toBe('page');
});

it('Agents reopens the agent and the profile beside it', async () => {
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=home&show=agents&agent=agt_support&panel=profile');
    await screen.findByTestId('agent-profile');

    view('DMs');
    await waitFor(() => expect(work.param('show')).toBe('dms'));
    expect(work.at('agent', 'panel')).toEqual([null, null]);

    view('Agents');
    await waitFor(() => expect(work.at('agent', 'panel')).toEqual(['agt_support', 'profile']));
    expect(await screen.findByTestId('agent-profile')).toBeTruthy();
});

it('DMs reopens the DM you last had open, not the newest', async () => {
    const fake = fakeWork();
    withSam(fake);
    const work = showWork(fake, '/dashboard?tab=work&space=ws_noclick&show=dms');
    // With nothing remembered it opens the newest.
    await waitFor(() => expect(work.param('channel')).toBe('dm_sam'));

    fireEvent.click(within(await screen.findByTestId('dms-list')).getByText('Priya Shah'));
    await waitFor(() => expect(work.param('channel')).toBe('dm_priya'));

    view('Home');
    await waitFor(() => expect(work.param('show')).toBeNull());
    expect(work.param('channel')).not.toBe('dm_priya');

    view('DMs');
    await waitFor(() => expect(work.at('show', 'channel')).toEqual(['dms', 'dm_priya']));
});

it('each space keeps its own: Agents in one space never reopens another’s agent', async () => {
    localStorage.setItem(VIEWS_KEY, JSON.stringify({ ws_noclick: { agents: { agent: 'agt_wirefern' } } }));
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=home&show=agents');
    fireEvent.click(await agentRow('agt_growth'));
    await waitFor(() => expect(work.param('agent')).toBe('agt_growth'));

    fireEvent.click(within(screen.getByRole('navigation', { name: 'Spaces' })).getByRole('button', { name: 'NoClick' }));
    await waitFor(() => expect(work.param('space')).toBe('ws_noclick'));
    await agentRow('agt_wirefern');
    view('Home');
    view('Agents');
    await waitFor(() => expect(work.param('agent')).toBe('agt_wirefern'));

    fireEvent.click(within(screen.getByRole('navigation', { name: 'Spaces' })).getByRole('button', { name: 'Rowan Hale' }));
    await waitFor(() => expect(work.param('space')).toBe('home'));
    await agentRow('agt_growth');
    view('Home');
    view('Agents');
    await waitFor(() => expect(work.param('agent')).toBe('agt_growth'));
});

it('a remembered agent that’s gone opens Agents with nothing open, its agents there to pick', async () => {
    localStorage.setItem(VIEWS_KEY, JSON.stringify({ home: { agents: { agent: 'agt_deleted' } } }));
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=home');
    // Where its agents stand is read: the rail counts what waits on you in Agents.
    await within(await screen.findByRole('navigation', { name: 'Views' })).findByText('2');

    view('Agents');
    const pane = await screen.findByTestId('agents-empty');
    expect(work.param('agent')).toBeNull();
    // Each of the space's agents, with what it's doing or last did; one opens on a click.
    const tile = await within(pane).findByTestId('agent-tile-agt_support');
    expect(tile.textContent).toContain('Support');
    expect(tile.textContent).toContain('2 things wait on you');
    fireEvent.click(tile);
    await waitFor(() => expect(work.param('agent')).toBe('agt_support'));
    expect(await screen.findByTestId('agent-conversation')).toBeTruthy();
});

it('an agent whose profile is beside wins over the one Agents remembers', async () => {
    localStorage.setItem(VIEWS_KEY, JSON.stringify({ ws_noclick: { agents: { agent: 'agt_growth' } } }));
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=ws_noclick&channel=ch_launch&agent=agt_support&panel=profile');
    await screen.findByTestId('agent-profile');

    view('Agents');
    await waitFor(() => expect(work.at('show', 'agent')).toEqual(['agents', 'agt_support']));
    expect(await screen.findByTestId('agent-conversation')).toBeTruthy();
});

it('a phone shows each view’s list, never what was last open in it', async () => {
    const lead = document.createElement('div');
    document.body.append(lead);
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=home&show=agents', (page) => (
        <PhoneBarSlotProvider slot={null} lead={lead} setLeadTaken={() => undefined}>
            {page}
        </PhoneBarSlotProvider>
    ));
    fireEvent.click(await agentRow('agt_growth'));
    await waitFor(() => expect(work.param('agent')).toBe('agt_growth'));

    fireEvent.click(await within(lead).findByRole('button', { name: 'Agents' }));
    await waitFor(() => expect(work.param('agent')).toBeNull());
    view('Home');
    await waitFor(() => expect(work.param('show')).toBeNull());
    view('Agents');
    await waitFor(() => expect(work.param('show')).toBe('agents'));
    expect(work.param('agent')).toBeNull();
    expect(await screen.findByTestId('agents-list')).toBeTruthy();
    lead.remove();
});

it('Agents in a space with none shows an agent’s face and the way to make one', async () => {
    const work = showWork(fakeWork({ empty: true, noclick: true }), '/dashboard?tab=work&space=home&show=agents');
    // Grey tiles while its agents are read, then a face (the channels layer's: its initials on a colour, unless a host
    // fills `channels.agent.face`).
    await screen.findByText('No agents in this space yet');
    const pane = screen.getByTestId('agents-empty');
    expect(pane.querySelector('[data-agent-initials]')).toBeTruthy();
    fireEvent.click(within(pane).getByRole('button', { name: 'Make an agent' }));
    await waitFor(() => expect(work.param('agent')).toBe('new'));
});

it('DMs with no one else here offers to invite someone', async () => {
    showWork(fakeWork({ empty: true, noclick: true }), '/dashboard?tab=work&space=home&show=dms');
    const pane = await screen.findByTestId('dms-empty');
    expect(pane.textContent).toContain('No one else is here yet');
    fireEvent.click(within(pane).getByRole('button', { name: 'Invite people' }));
    expect(await screen.findByTestId('invite-dialog')).toBeTruthy();
});

it('DMs with people but no DM yet starts one from New message', async () => {
    const fake = fakeWork();
    fake.channels.splice(
        fake.channels.findIndex((c) => c.id === 'dm_priya'),
        1
    );
    const work = showWork(fake, '/dashboard?tab=work&space=ws_noclick&show=dms');
    const pane = await screen.findByTestId('dms-empty');
    await within(pane).findByText('No messages yet');
    fireEvent.keyDown(within(pane).getByRole('button', { name: 'New message' }), { key: 'Enter' });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Priya Shah/ }));
    await waitFor(() => expect(fake.requests.some((r) => r.method === 'POST' && r.path === '/v1/channels' && (r.body as { kind?: string }).kind === 'dm')).toBe(true));
    await waitFor(() => expect(work.param('channel')).toMatch(/^dm_/));
});

it('Home linked to a channel that’s gone shows the space’s channels to open, never a blank pane', async () => {
    const work = showWork(fakeWork(), '/dashboard?tab=work&space=ws_noclick&channel=ch_gone');
    const pane = await screen.findByTestId('home-empty');
    expect(pane.textContent).toContain('Start a channel');
    fireEvent.click(within(pane).getByRole('button', { name: 'Open #incidents' }));
    await waitFor(() => expect(work.param('channel')).toBe('ch_incidents'));
});

it('DMs linked to a DM that’s gone shows the newest to pick up again', async () => {
    const fake = fakeWork();
    withSam(fake);
    const work = showWork(fake, '/dashboard?tab=work&space=ws_noclick&show=dms&channel=dm_gone');
    const pane = await screen.findByTestId('dms-empty');
    const tiles = within(pane).getAllByRole('button', { name: /^Your messages with / });
    expect(tiles.map((t) => t.getAttribute('aria-label'))).toEqual(['Your messages with Sam Rivera', 'Your messages with Priya Shah']);
    fireEvent.click(tiles[1]);
    await waitFor(() => expect(work.param('channel')).toBe('dm_priya'));
});
