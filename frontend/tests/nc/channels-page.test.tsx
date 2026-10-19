// Channels in the running app, over a fake transport: the rail holds your own
// channels and a workspace, a channel opens on its newest messages (and is
// marked read), what you post and your reaction go through the transport, a
// slash command changes the channel, and a live change reads in an agent's
// reply. Nothing reaches the platform; preview() leaves the page mounted for
// visual checks.
import { createRoot } from 'react-dom/client';
import { createRoutesStub } from 'react-router';
import { flushSync } from 'react-dom';
import { ChannelsView } from '~/components/shell/ChannelsPage';
import type { ChannelChange, ChannelsTransport } from '~/components/shell/channels/platform';
import type { Channel, ChannelMessage } from '~/components/shell/channels/types';
import { nc } from '~/lib/nc';

const at = (minute: number) => new Date(Date.now() - (60 - minute) * 60_000).toISOString();
const SCOUT = { type: 'agent' as const, id: 'agt_scout', name: 'Scout' };
const ME = { type: 'account' as const, id: null, name: 'owner' };
const msg = (id: string, text: string, author: ChannelMessage['author'], minute: number, extra: Partial<ChannelMessage> = {}): ChannelMessage => ({
    id,
    author,
    text,
    at: at(minute),
    attachments: [],
    reactions: [],
    mentions: [],
    ...extra,
});

const LAUNCH: Channel = {
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
};

type Call = [string, ...unknown[]];

function fakeTransport(calls: Call[]) {
    let listener: ((change: ChannelChange) => void) | null = null;
    let channels: Channel[] = [LAUNCH, { ...LAUNCH, id: 'ch_billing', name: 'billing', workspaceId: 'ws_acme', members: [], unread: 1 }];
    const newest = [msg('m1', '@Scout what are people saying?', ME, 10), msg('m2', 'Three threads worth reading.', SCOUT, 12, { mentions: [] })];
    let later: ChannelMessage[] = [];
    const transport: ChannelsTransport = {
        workspaces: async () => [{ id: 'ws_acme', name: 'Acme Corp' }],
        channels: async () => channels,
        agents: async () => [
            { id: 'agt_scout', source: 'platform', name: 'Scout' },
            { id: 'agt_quill', source: 'platform', name: 'Quill' },
        ],
        history: async () => ({ messages: newest, older: null }),
        after: async () => later,
        message: async (_c, id) => newest.find((m) => m.id === id) as ChannelMessage,
        upload: async (_c, file) => ({ id: 'att_1', kind: 'file', name: file.name, mimeType: file.type, sizeBytes: file.size }),
        post: async (_c, text, ids) => {
            calls.push(['post', text, ids]);
            return msg(`p${calls.length}`, text, ME, 50);
        },
        react: async (_c, id, emoji, on) => {
            calls.push(['react', id, emoji, on]);
            return { ...(newest.find((m) => m.id === id) as ChannelMessage), reactions: on ? [{ emoji, count: 1, mine: true, names: ['You'] }] : [] };
        },
        createWorkspace: async (name) => ({ id: 'ws_new', name }),
        createChannel: async (input) => ({ ...LAUNCH, id: 'ch_new', name: input.name }),
        updateChannel: async (id, changes) => {
            calls.push(['updateChannel', id, changes]);
            channels = channels.map((c) => (c.id === id ? { ...c, ...changes } : c));
            return channels.find((c) => c.id === id) as Channel;
        },
        addAgent: async (channel) => channel,
        removeMember: async (id) => channels.find((c) => c.id === id) as Channel,
        close: async () => undefined,
        markRead: async (id) => {
            calls.push(['markRead', id]);
        },
        subscribe: (l) => {
            listener = l;
            return () => {
                listener = null;
            };
        },
    };
    return {
        transport,
        replyLive(text: string) {
            later = [msg('m3', text, SCOUT, 55)];
            listener?.({ kind: 'message', channelId: 'ch_launch' });
        },
    };
}

let cleanup: (() => void) | undefined;

function mount(calls: Call[]) {
    cleanup?.();
    const host = document.createElement('div');
    host.id = 'channels-page-test';
    Object.assign(host.style, { position: 'fixed', inset: '0', zIndex: '9999', overflow: 'hidden', background: 'hsl(var(--background))' });
    document.body.appendChild(host);
    const fake = fakeTransport(calls);
    const Page = () => <ChannelsView user={{ email: 'dana@example.com', display_name: 'Dana Ruiz' }} transport={fake.transport} agentsHref="/dashboard/developers" />;
    const App = createRoutesStub([{ path: '/', Component: Page }]);
    const root = createRoot(host);
    flushSync(() => root.render(<App initialEntries={['/?channel=ch_launch']} />));
    cleanup = () => {
        root.unmount();
        host.remove();
        cleanup = undefined;
    };
    return { host, fake };
}

export async function preview() {
    mount([]);
    await nc.wait.forElement('#channels-page-test [data-testid="channel-message"]');
    return { mounted: true };
}

export function closePreview() {
    cleanup?.();
}

function send(host: HTMLElement, text: string) {
    const box = host.querySelector<HTMLTextAreaElement>('textarea[aria-label^="Message #"]')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    setter.call(box, text);
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}

const texts = (host: HTMLElement) => Array.from(host.querySelectorAll('[data-testid="channel-message"]')).map((m) => m.textContent ?? '');

export default async function () {
    const calls: Call[] = [];
    const { host, fake } = mount(calls);
    try {
        await nc.wait.forElement('#channels-page-test [data-testid="channel-message"]');
        const tiles = Array.from(host.querySelectorAll('[data-testid="workspace-tile"]')).map((t) => t.getAttribute('aria-label'));
        nc.assert.equal(tiles.length, 2, 'your own channels and the workspace each have a tile');
        nc.assert.ok(texts(host).some((t) => t.includes('Three threads worth reading.')), 'the channel opens on its newest messages');
        await nc.wait.until(() => calls.some((c) => c[0] === 'markRead' && c[1] === 'ch_launch'), 2000);

        send(host, 'Ship it Tuesday.');
        await nc.wait.until(() => calls.some((c) => c[0] === 'post' && c[1] === 'Ship it Tuesday.'), 2000);
        await nc.wait.until(() => texts(host).some((t) => t.includes('Ship it Tuesday.')), 2000);

        send(host, '/topic Post-launch');
        await nc.wait.until(() => calls.some((c) => c[0] === 'updateChannel'), 2000);
        nc.assert.ok(host.textContent?.includes('Post-launch') ?? false, 'the new topic shows in the header');

        fake.replyLive('Drafted the post.');
        await nc.wait.until(() => texts(host).some((t) => t.includes('Drafted the post.')), 3000);
        return { posted: calls.filter((c) => c[0] === 'post').length, live: true };
    } finally {
        cleanup?.();
    }
}
