// @vitest-environment jsdom
// Channels over a platform registered as the hosted service registers its own,
// with a fake transport holding the account's workspaces, channels, agents and
// messages: the rail holds your own channels and each workspace, a channel
// shows its unread count until opened (and is marked read on the server), its
// history pages back, posting, files, reactions and the slash commands go
// through the transport, a live change reads in what landed, and the members'
// picker offers the agents in your Automations beside your platform agents.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import type { ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/askNoClick', () => ({ askNoClick: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ChannelsPage } from '~/components/shell/ChannelsPage';
import { PlatformChannelsContext, registerPlatformChannels, type ChannelChange, type ChannelsTransport } from '~/components/shell/channels/platform';
import type { AgentChoice, Channel, ChannelMember, ChannelMessage, ChannelSchedule, ChannelWorkspace } from '~/components/shell/channels/types';
import { askNoClick } from '~/lib/askNoClick';

const USER = { email: 'dana@example.com', display_name: 'Dana Ruiz' };
const at = (minute: number) => new Date(Date.UTC(2026, 9, 9, 9, minute)).toISOString();

function message(id: string, text: string, author: ChannelMessage['author'], minute: number, extra: Partial<ChannelMessage> = {}): ChannelMessage {
    return { id, author, text, at: at(minute), attachments: [], reactions: [], mentions: [], ...extra };
}

const SCOUT = { type: 'agent' as const, id: 'agt_scout', name: 'Scout' };
const ME = { type: 'account' as const, id: null, name: 'owner' };

class FakePlatform implements ChannelsTransport {
    workspaceRows: ChannelWorkspace[] = [{ id: 'ws_acme', name: 'Acme Corp' }];
    channelRows: Channel[] = [
        {
            id: 'ch_launch',
            name: 'launch',
            topic: "Friday's launch",
            mode: 'mentions',
            status: 'open',
            haltReason: null,
            workspaceId: null,
            members: [{ id: 'mem_scout', kind: 'agent', name: 'Scout', agentId: 'agt_scout' }],
            unread: 2,
            createdAt: at(0),
        },
        {
            id: 'ch_notes',
            name: 'notes',
            topic: '',
            mode: 'all',
            status: 'open',
            haltReason: null,
            workspaceId: null,
            members: [],
            unread: 0,
            createdAt: at(1),
        },
        { id: 'ch_billing', name: 'billing', topic: '', mode: 'mentions', status: 'open', haltReason: null, workspaceId: 'ws_acme', members: [], unread: 4, createdAt: at(2) },
    ];
    agentRows: AgentChoice[] = [
        { id: 'agt_scout', source: 'platform', name: 'Scout' },
        { id: 'agt_quill', source: 'platform', name: 'Quill' },
        { id: 'wf_content:writer', source: 'automation', name: 'Writer', workflowId: 'wf_content', nodeId: 'writer', workflowName: 'Content' },
    ];
    older: ChannelMessage[] = [message('m0', 'Kickoff notes are in the doc.', ME, 1)];
    newest: ChannelMessage[] = [
        message('m1', '@Scout what are people saying?', ME, 2),
        message('m2', 'Three threads worth reading.', SCOUT, 3, { reactions: [{ emoji: '👍', count: 1, mine: true, names: ['You'] }] }),
    ];
    listeners = new Set<(change: ChannelChange) => void>();
    calls: { method: string; args: unknown[] }[] = [];
    scheduleRows: ChannelSchedule[] = [];

    /** A change the server pushes, to everyone following. */
    push(change: ChannelChange) {
        this.listeners.forEach((listener) => listener(change));
    }

    private call(method: string, ...args: unknown[]) {
        this.calls.push({ method, args });
    }
    called(method: string) {
        return this.calls.filter((c) => c.method === method).map((c) => c.args);
    }

    workspaces = vi.fn(async () => this.workspaceRows);
    channels = vi.fn(async () => this.channelRows);
    agents = vi.fn(async () => this.agentRows);
    history = vi.fn(async (_channelId: string, before?: string) => (before ? { messages: this.older, older: null } : { messages: this.newest, older: 'm1' }));
    after = vi.fn(async (): Promise<ChannelMessage[]> => []);
    message = vi.fn(async (_c: string, id: string) => this.newest.find((m) => m.id === id) as ChannelMessage);
    upload = vi.fn(async (_c: string, file: File) => ({ id: 'att_1', kind: 'file' as const, name: file.name, mimeType: file.type, sizeBytes: file.size, url: 'https://assets.test/att_1' }));
    post = vi.fn(async (_c: string, text: string, attachmentIds: string[]) => {
        this.call('post', text, attachmentIds);
        return message(`posted-${this.calls.length}`, text, ME, 30);
    });
    react = vi.fn(async (_c: string, id: string, emoji: string, on: boolean) => {
        this.call('react', id, emoji, on);
        const found = this.newest.find((m) => m.id === id) as ChannelMessage;
        return { ...found, reactions: on ? [{ emoji, count: 1, mine: true, names: ['You'] }] : [] };
    });
    createWorkspace = vi.fn(async (name: string) => ({ id: 'ws_new', name }));
    createChannel = vi.fn(async (input: { workspaceId: string | null; name: string; topic: string; mode: Channel['mode']; agents: AgentChoice[] }) => {
        const made: Channel = { ...this.channelRows[1], id: 'ch_new', name: input.name, topic: input.topic, workspaceId: input.workspaceId, createdAt: at(40) };
        this.channelRows = [...this.channelRows, made];
        return made;
    });
    updateChannel = vi.fn(async (channelId: string, changes: { topic?: string; mode?: Channel['mode'] }) => {
        this.call('updateChannel', channelId, changes);
        const updated = { ...(this.channelRows.find((c) => c.id === channelId) as Channel), ...changes };
        this.channelRows = this.channelRows.map((c) => (c.id === channelId ? updated : c));
        return updated;
    });
    addAgent = vi.fn(async (channel: Channel, agent: AgentChoice) => {
        this.call('addAgent', channel.id, agent.id);
        const member: ChannelMember =
            agent.source === 'automation'
                ? { id: `mem_${agent.nodeId}`, kind: 'agent', name: agent.name, workflowId: agent.workflowId, nodeId: agent.nodeId, workflowName: agent.workflowName }
                : { id: `mem_${agent.id}`, kind: 'agent', name: agent.name, agentId: agent.id };
        const updated = { ...channel, members: [...channel.members, member] };
        this.channelRows = this.channelRows.map((c) => (c.id === channel.id ? updated : c));
        return updated;
    });
    removeMember = vi.fn(async (channelId: string) => this.channelRows.find((c) => c.id === channelId) as Channel);
    close = vi.fn(async () => undefined);
    markRead = vi.fn(async () => undefined);
    schedules = vi.fn(async () => this.scheduleRows);
    subscribe = (listener: (change: ChannelChange) => void) => {
        this.listeners.add(listener);
        return () => {
            this.listeners.delete(listener);
        };
    };
}

let platform: FakePlatform;

function Fake({ children }: { children: ReactNode }) {
    return <PlatformChannelsContext.Provider value={{ transport: platform, agentsHref: '/dashboard/developers' }}>{children}</PlatformChannelsContext.Provider>;
}

beforeAll(() => {
    registerPlatformChannels(Fake);
    if (!URL.createObjectURL) URL.createObjectURL = () => 'blob:local';
    if (!URL.revokeObjectURL) URL.revokeObjectURL = () => undefined;
    Element.prototype.scrollIntoView ??= () => undefined;
    window.matchMedia ??= (query: string) =>
        ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) as MediaQueryList;
});
beforeEach(() => {
    platform = new FakePlatform();
    vi.mocked(askNoClick).mockClear();
});
afterEach(cleanup);

function renderAt(search: string) {
    return render(
        <MemoryRouter initialEntries={[`/dashboard?tab=channels${search}`]}>
            <ChannelsPage user={USER} />
        </MemoryRouter>
    );
}

/** A message in the channel says `text` (mentions and #channels render as their own elements). */
async function shows(text: string) {
    await waitFor(() => expect(screen.getAllByTestId('channel-message').map((m) => m.textContent).join(' | ')).toContain(text));
}

async function send(text: string) {
    const box = await screen.findByRole('textbox', { name: /Message #/ });
    fireEvent.change(box, { target: { value: text } });
    fireEvent.keyDown(box, { key: 'Enter' });
}

describe('Channels on the platform', () => {
    it('lists your own channels and each workspace, with what is unread, and marks an opened channel read', async () => {
        renderAt('&channel=ch_notes');
        const rail = await screen.findByRole('navigation', { name: 'Workspaces' });
        const tiles = within(rail).getAllByTestId('workspace-tile');
        expect(tiles.map((t) => t.getAttribute('aria-label'))).toEqual(['Dana Ruiz, 2 unread', 'Acme Corp, 4 unread']);
        const list = screen.getByRole('navigation', { name: 'Channels' });
        expect(within(list).getByRole('button', { name: /launch\s*2/ })).toBeTruthy();
        expect(within(list).queryByText('billing')).toBeNull();
        expect(screen.queryByText(/samples/)).toBeNull();

        fireEvent.click(within(list).getByRole('button', { name: /launch/ }));
        expect(await screen.findByText('Three threads worth reading.')).toBeTruthy();
        await waitFor(() => expect(platform.markRead).toHaveBeenCalledWith('ch_launch'));
        expect(within(list).getByRole('button', { name: /^launch$/ })).toBeTruthy();
    });

    it('pages back through history and keeps a live channel current', async () => {
        renderAt('&channel=ch_launch');
        expect(await screen.findByText('Three threads worth reading.')).toBeTruthy();
        fireEvent.click(screen.getByTestId('load-older'));
        expect(await screen.findByText('Kickoff notes are in the doc.')).toBeTruthy();
        expect(platform.history).toHaveBeenLastCalledWith('ch_launch', 'm1');
        expect(screen.queryByTestId('load-older')).toBeNull();

        platform.after.mockResolvedValueOnce([message('m3', 'Drafted the post.', SCOUT, 5)]);
        act(() => platform.push({ kind: 'message', channelId: 'ch_launch' }));
        expect(await screen.findByText('Drafted the post.')).toBeTruthy();
        expect(platform.after).toHaveBeenCalledWith('ch_launch', 'm2');
    });

    it('posts what you write, and flips your reaction', async () => {
        renderAt('&channel=ch_launch');
        await screen.findByText('Three threads worth reading.');
        await send('Ship it Tuesday.');
        await waitFor(() => expect(platform.called('post')).toEqual([['Ship it Tuesday.', []]]));
        expect(await screen.findByText('Ship it Tuesday.')).toBeTruthy();

        fireEvent.click(screen.getByRole('button', { name: /👍 1, yours/ }));
        await waitFor(() => expect(platform.called('react')).toEqual([['m2', '👍', false]]));
    });

    it('uploads an attached file and posts it with the message', async () => {
        renderAt('&channel=ch_launch');
        await screen.findByText('Three threads worth reading.');
        const file = new File(['%PDF-1.4'], 'report.pdf', { type: 'application/pdf' });
        fireEvent.change(screen.getByTestId('channel-file-input'), { target: { files: [file] } });
        await waitFor(() => expect(platform.upload).toHaveBeenCalledWith('ch_launch', file, undefined));
        const box = await screen.findByRole('textbox', { name: /Message #/ });
        fireEvent.change(box, { target: { value: '@Scout read this' } });
        // Send waits for the upload to land.
        await waitFor(() => expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(screen.getByRole('button', { name: 'Send' }));
        await waitFor(() => expect(platform.called('post')).toEqual([['@Scout read this', ['att_1']]]));
    });

    it('runs slash commands through the platform, and answers you alone where it should', async () => {
        renderAt('&channel=ch_launch');
        await screen.findByText('Three threads worth reading.');
        await send('/topic Post-launch');
        await waitFor(() => expect(platform.called('updateChannel')).toEqual([['ch_launch', { topic: 'Post-launch' }]]));
        await send('/mode all');
        await waitFor(() => expect(platform.called('updateChannel').at(-1)).toEqual(['ch_launch', { mode: 'all' }]));
        await send('/invite @Quill');
        await waitFor(() => expect(platform.called('addAgent')).toEqual([['ch_launch', 'agt_quill']]));
        await shows('@Quill joined #launch.');
        await send('/handoff @Scout draft the post');
        await waitFor(() => expect(platform.called('post')).toEqual([['@Scout draft the post', []]]));
        await send('/remind me to check in at 3pm');
        expect(askNoClick).toHaveBeenCalledWith(expect.stringContaining('Remind me to check in at 3pm'));
        await send('/summarize ');
        await shows("Here's where #launch stands");
        expect(screen.getAllByText('Only visible to you').length).toBeGreaterThan(0);
        await send('/dance');
        await shows("`/dance` isn't a command here".replace(/`/g, ''));
    });

    it('offers the agents in your Automations beside your platform agents, and adds one through the transport', async () => {
        renderAt('&channel=ch_launch');
        await screen.findByText('Three threads worth reading.');
        fireEvent.click(screen.getByTestId('channel-members'));
        const yours = await screen.findByRole('region', { name: 'Your agents' });
        const writer = within(yours).getByRole('button', { name: /Writer/ });
        expect(writer.textContent).toContain('Content');
        // Scout is in the room already; Quill isn't.
        const theirs = screen.getByRole('region', { name: 'Platform agents' });
        expect(within(theirs).getAllByRole('button').map((b) => b.textContent?.slice(1))).toEqual(['Quill']);

        fireEvent.click(writer);
        await waitFor(() => expect(platform.called('addAgent')).toEqual([['ch_launch', 'wf_content:writer']]));
        expect(platform.addAgent.mock.calls[0][1]).toMatchObject({ source: 'automation', workflowId: 'wf_content', nodeId: 'writer' });
        await shows('@Writer joined #launch.');
        // In the room, it says which automation it is, and it's no longer offered.
        expect(await screen.findByText('Agent in Content')).toBeTruthy();
        expect(screen.queryByRole('region', { name: 'Your agents' })).toBeNull();

        // Its reply reads as its own, with its workflow beside its name.
        platform.after.mockResolvedValueOnce([message('m3', 'Drafted the post.', { type: 'workflow_agent', id: 'mem_writer', name: 'Writer' }, 5)]);
        act(() => platform.push({ kind: 'message', channelId: 'ch_launch' }));
        const reply = (await screen.findByText('Drafted the post.')).closest('[data-testid="channel-message"]') as HTMLElement;
        expect(within(reply).getByText('Content')).toBeTruthy();
    });

    it('reads a hand-off as one, signs a post an agent made for you by that agent, and says when the channel posts on its own', async () => {
        const viewer = Intl.DateTimeFormat().resolvedOptions().timeZone;
        platform.scheduleRows = [{ id: 'trg_1', cron: '0 8 * * 1', tz: viewer, message: '@Scout gather this week’s threads', nextRun: '2026-11-02T14:00:00.000Z' }];
        platform.channelRows[0].members.push({ id: 'mem_quill', kind: 'agent', name: 'Quill', agentId: 'agt_quill' });
        platform.newest = [
            // Your assistant setting the room going: the account's post, made by an agent.
            message('m1', '@Scout gather this week’s threads, then hand them to @Quill.', { type: 'account', id: 'agt_assistant', name: 'NoClick' }, 2, { mentions: ['Scout', 'Quill'] }),
            message('m2', 'Three threads worth reading. @Quill, over to you.', SCOUT, 3, { mentions: ['Quill'] }),
            message('m3', 'Ship it.', ME, 4),
        ];
        platform.history = vi.fn(async () => ({ messages: platform.newest, older: null }));
        renderAt('&channel=ch_launch');

        const handoff = await screen.findByTestId('channel-handoff');
        expect(handoff.textContent).toBe('SQHanded off toQuill');
        expect(handoff.closest('[data-testid="channel-message"]')?.textContent).toContain('Three threads worth reading.');
        // Only an agent's message hands work on; the room being set going is no hand-off.
        expect(screen.getAllByTestId('channel-handoff')).toHaveLength(1);

        const [kickoff, , yours] = screen.getAllByTestId('channel-message');
        expect(kickoff.textContent).toMatch(/^N?NoClickfor you/);
        expect(kickoff.textContent).not.toContain('You');
        expect(within(yours).getByText('You')).toBeTruthy();

        await waitFor(() => expect(screen.getByTestId('channel-schedule').textContent).toBe('Every Monday at 8:00 AM'));
        const line = screen.getByTestId('channel-schedule-line');
        expect(line.textContent).toBe('Every Monday at 8:00 AMposts “@Scout gather this week’s threads”');
        expect(platform.schedules).toHaveBeenCalledWith('ch_launch');

        // A schedule added later shows once the channel says it changed.
        platform.scheduleRows = [...platform.scheduleRows, { id: 'trg_2', cron: '0 17 * * 5', tz: viewer, message: '@Quill wrap up the week', nextRun: null }];
        act(() => platform.push({ kind: 'channel', channelId: 'ch_launch' }));
        await waitFor(() => expect(screen.getAllByTestId('channel-schedule-line')).toHaveLength(2));
        expect(screen.getByTestId('channel-schedule').textContent).toBe('Every Monday at 8:00 AM+1');
    });

    it('starts a channel in the workspace you are in', async () => {
        renderAt('&channel=ch_billing');
        await screen.findByRole('heading', { name: 'billing' });
        fireEvent.click(screen.getByTestId('new-channel'));
        const dialog = await screen.findByTestId('new-channel-dialog');
        fireEvent.change(within(dialog).getByPlaceholderText('launch-plans'), { target: { value: 'Q4 Planning' } });
        expect(within(dialog).getByText('Saved as #q4-planning')).toBeTruthy();
        fireEvent.click(within(dialog).getByRole('checkbox', { name: /Quill/ }));
        fireEvent.click(within(dialog).getByRole('button', { name: 'Start channel' }));
        await waitFor(() =>
            expect(platform.createChannel).toHaveBeenCalledWith({ name: 'q4-planning', topic: '', mode: 'mentions', agents: [platform.agentRows[1]], workspaceId: 'ws_acme' })
        );
    });

    it('says why the channels could not be read', async () => {
        platform.channels.mockRejectedValueOnce(new Error('The NoClick API is part of the paid plans. Upgrade to Plus or Pro.'));
        renderAt('');
        expect(await screen.findByText('The NoClick API is part of the paid plans. Upgrade to Plus or Pro.')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
        expect(await screen.findByRole('navigation', { name: 'Channels' })).toBeTruthy();
    });
});
