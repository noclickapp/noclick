// The channels transport over a fake API: what it reads (the account's own workspaces and its channels, open and
// closed, history from the newest), how the platform's objects become the page's (your reactions, files, members),
// what each write sends (an agent joins a workspace before its channel, an agent from elsewhere joins through
// MORE_AGENTS, never the API), saying you're typing, and that a failure becomes the sentence to show.
import { describe, expect, it } from 'vitest';
import { NoClick } from 'noclick';
import { ChannelNameTaken } from './transport';
import type { Channel } from './types';
import type { MoreAgentChoice, MoreAgents } from './slots';
import { changeOf, platformTransport, sdkTyping, typingChangeOf } from './sdkTransport';

type Reply = unknown | ((body: unknown, url: URL) => unknown);

const WRITER: MoreAgentChoice = { id: 'wf_1:writer', source: 'automation', name: 'Writer', markType: 'agent:claude-code', workflowId: 'wf_1', nodeId: 'writer', workflowName: 'Content' };

/** Agents from elsewhere, faked: one to offer, and what it was asked to add. */
function moreAgents(): MoreAgents & { added: [string, string][] } {
    const added: [string, string][] = [];
    return {
        added,
        label: 'Your agents',
        list: async () => [WRITER],
        add: async (channelId, agent) => {
            added.push([channelId, agent.id]);
        },
    };
}

function api(routes: Record<string, Reply>, more: ReturnType<typeof moreAgents> | null = moreAgents()) {
    const calls: { method: string; path: string; query: Record<string, string>; body: unknown }[] = [];
    const fetch: typeof globalThis.fetch = async (input, init = {}) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = init.method ?? 'GET';
        const body = typeof init.body === 'string' ? JSON.parse(init.body) : (init.body ?? null);
        calls.push({ method, path: url.pathname, query: Object.fromEntries(url.searchParams), body });
        const route = routes[`${method} ${url.pathname}`];
        if (route === undefined) return new Response(JSON.stringify({ error: { type: 'not_found', message: `No route ${method} ${url.pathname}` } }), { status: 404 });
        const reply = typeof route === 'function' ? (route as (b: unknown, u: URL) => unknown)(body, url) : route;
        if (reply instanceof Response) return reply;
        return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } });
    };
    const client = new NoClick({ apiKey: 'test-token', baseUrl: 'https://api.test', fetch, maxRetries: 0 });
    return { transport: platformTransport(client, { moreAgents: more, sendTyping: sdkTyping(client) }), calls, more };
}

const list = (...data: unknown[]) => ({ object: 'list', data, next_cursor: null });

const CHANNEL = {
    object: 'channel', id: 'ch_1', name: 'launch', topic: "Friday's launch", mode: 'all', status: 'halted', halt_reason: 'Stopped after 20 agent turns without a person.',
    unread_count: 3, user_id: null, workspace_id: 'ws_1', created_at: '2026-10-09T09:00:00+00:00',
    members: [
        { object: 'channel_member', id: 'mem_1', type: 'agent', name: 'Scout', agent_id: 'agt_1', busy: true },
        { object: 'channel_member', id: 'mem_2', type: 'a2a', name: 'partner', a2a_url: 'https://a.example/a2a', busy: false },
    ],
};
const MESSAGE = {
    object: 'channel_message', id: 'm2', channel_id: 'ch_1', author: { type: 'agent', id: 'agt_1', name: 'Scout' }, text: 'Done, @partner?', mentions: ['partner'],
    created_at: '2026-10-09T09:05:00.123456+00:00',
    attachments: [
        { object: 'channel_attachment', id: 'att_1', name: 'Voice clip.mp3', mime_type: 'audio/mpeg', size_bytes: 9000, kind: 'audio', url: 'https://assets.test/a/Voice%20clip.mp3', voice: true, duration_ms: 4200, peaks: [0.2, 1] },
    ],
    reactions: [{ emoji: '🎉', count: 2, by: [{ type: 'account', id: null, name: 'owner' }, { type: 'agent', id: 'agt_1', name: 'Scout' }] }],
};

describe('the platform transport', () => {
    it("reads the account's own channels, open and closed, and maps members, status and unread", async () => {
        const { transport, calls } = api({ 'GET /v1/channels': list(CHANNEL) });
        const [channel] = await transport.channels();
        expect(calls[0].query).toEqual({ user_id: 'none', limit: '100' });
        expect(channel).toMatchObject({ id: 'ch_1', name: 'launch', topic: "Friday's launch", mode: 'all', status: 'halted', workspaceId: 'ws_1', unread: 3 });
        expect(channel.haltReason).toBe('Stopped after 20 agent turns without a person.');
        expect(channel.members.map((m) => [m.kind, m.name, m.agentId, m.busy])).toEqual([
            ['agent', 'Scout', 'agt_1', true],
            ['outside', 'partner', undefined, false],
        ]);
    });

    it('stars, mutes, leaves and reopens a channel, each answered by the channel as you read it', async () => {
        const at = (extra: object) => ({ ...CHANNEL, status: 'open', halt_reason: null, ...extra });
        const { transport, calls } = api({
            'POST /v1/channels/ch_1/star': at({ starred: true }),
            'DELETE /v1/channels/ch_1/mute': at({ muted: false, unread_count: 3 }),
            'POST /v1/channels/ch_1/leave': { object: 'channel_membership', action: 'removed' },
            'POST /v1/channels/ch_1/reopen': (body: unknown) =>
                (body as { name?: string }).name
                    ? at({ name: (body as { name: string }).name })
                    : new Response(JSON.stringify({ error: { type: 'conflict', message: 'An open channel here is called #launch already.' } }), { status: 409 }),
        });
        expect(await transport.setPreference('ch_1', 'starred', true)).toMatchObject({ starred: true, muted: false });
        expect(await transport.setPreference('ch_1', 'muted', false)).toMatchObject({ muted: false, unread: 3 });
        await transport.leave('ch_1');
        // Its name taken: a reopen says so in a kind of its own, and reopens under another.
        await expect(transport.reopen('ch_1')).rejects.toBeInstanceOf(ChannelNameTaken);
        await expect(transport.reopen('ch_1')).rejects.toThrow('An open channel here is called #launch already.');
        expect(await transport.reopen('ch_1', 'launch-2')).toMatchObject({ name: 'launch-2', status: 'open' });
        expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
            'POST /v1/channels/ch_1/star',
            'DELETE /v1/channels/ch_1/mute',
            'POST /v1/channels/ch_1/leave',
            'POST /v1/channels/ch_1/reopen',
            'POST /v1/channels/ch_1/reopen',
            'POST /v1/channels/ch_1/reopen',
        ]);
    });

    it('reads what @-mentions you where the platform counts it, and joins a channel again', async () => {
        const { transport, calls } = api({
            'GET /v1/channels': list({ ...CHANNEL, mention_count: 2 }, { ...CHANNEL, id: 'ch_2' }),
            'POST /v1/channels/ch_1/join': { ...CHANNEL, status: 'open', mention_count: 0 },
        });
        const [counted, uncounted] = await transport.channels();
        expect(counted.mentions).toBe(2);
        // A platform that doesn't count them says nothing, never zero.
        expect(uncounted.mentions).toBeUndefined();
        expect(await transport.join('ch_1')).toMatchObject({ id: 'ch_1', mentions: 0 });
        expect(calls.slice(1).map((c) => `${c.method} ${c.path}`)).toEqual(['POST /v1/channels/ch_1/join']);
    });

    it('reads the schedules that post in a channel', async () => {
        const cron = {
            object: 'agent_trigger', id: 'trg_1', agent_id: null, channel_id: 'ch_1', kind: 'cron', status: 'active', url: null, last_fired_at: null, error: null,
            spec: { cron: '0 8 * * 1', tz: 'America/Chicago', message: '@Scout find this week’s events' }, next_run: '2026-11-02T14:00:00+00:00', created_at: '2026-10-27T09:16:03+00:00',
        };
        const { transport, calls } = api({ 'GET /v1/channels/ch_1/triggers': list(cron) });
        expect(await transport.schedules('ch_1')).toEqual([{ id: 'trg_1', cron: '0 8 * * 1', tz: 'America/Chicago', message: '@Scout find this week’s events', nextRun: '2026-11-02T14:00:00.000Z' }]);
        expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /v1/channels/ch_1/triggers']);
    });

    it('reads history from the newest and back, with your reactions and the files a message carries', async () => {
        const { transport, calls } = api({ 'GET /v1/channels/ch_1/messages': { object: 'list', data: [MESSAGE], next_cursor: 'm2' } });
        const page = await transport.history('ch_1');
        expect(calls[0].query).toEqual({ newest: 'true', limit: '50' });
        expect(page.older).toBe('m2');
        const [message] = page.messages;
        expect(message.at).toBe('2026-10-09T09:05:00.123456+00:00');
        expect(message.author).toEqual({ type: 'agent', id: 'agt_1', name: 'Scout' });
        expect(message.reactions).toEqual([{ emoji: '🎉', count: 2, mine: true, names: ['You', 'Scout'] }]);
        expect(message.attachments).toEqual([
            { id: 'att_1', kind: 'audio', name: 'Voice clip.mp3', mimeType: 'audio/mpeg', sizeBytes: 9000, url: 'https://assets.test/a/Voice%20clip.mp3', voice: true, durationMs: 4200, peaks: [0.2, 1] },
        ]);
        await transport.history('ch_1', 'm2');
        expect(calls[1].query).toEqual({ before: 'm2', limit: '50' });
    });

    it('uploads a voice clip with its waveform, posts it, and reacts or takes a reaction back', async () => {
        const { transport, calls } = api({
            'POST /v1/channels/ch_1/attachments': MESSAGE.attachments[0],
            'POST /v1/channels/ch_1/messages': MESSAGE,
            'POST /v1/channels/ch_1/messages/m2/reactions': MESSAGE,
            [`DELETE /v1/channels/ch_1/messages/m2/reactions/${encodeURIComponent('🎉')}`]: { ...MESSAGE, reactions: [] },
        });
        const clip = new File([new Uint8Array([1, 2])], 'Voice clip.webm', { type: 'audio/webm' });
        const attachment = await transport.upload('ch_1', clip, { durationMs: 4200, peaks: [0.2, 1] });
        expect(calls[0].query).toEqual({ name: 'Voice clip.webm', mime_type: 'audio/webm', voice: 'true', peaks: '0.2,1' });
        expect(attachment.id).toBe('att_1');
        await transport.post('ch_1', 'Listen', ['att_1']);
        expect(calls[1].body).toEqual({ text: 'Listen', attachments: ['att_1'] });
        await transport.react('ch_1', 'm2', '🎉', true);
        expect(calls[2].body).toEqual({ emoji: '🎉' });
        expect((await transport.react('ch_1', 'm2', '🎉', false)).reactions).toEqual([]);
        expect(calls[3].method).toBe('DELETE');
    });

    it('takes an agent into a workspace before its channel, and starts a channel there the same way', async () => {
        const workspace = { object: 'workspace', id: 'ws_1', name: 'Acme', logo_url: null, user_id: null, status: 'active', members: [{ id: 'wm_1', type: 'agent', agent_id: 'agt_1' }] };
        const { transport, calls } = api({
            'GET /v1/workspaces/ws_1': workspace,
            'POST /v1/workspaces/ws_1/members': { id: 'wm_2', type: 'agent', agent_id: 'agt_2' },
            'POST /v1/channels/ch_1/members': { id: 'mem_3', type: 'agent', agent_id: 'agt_2', name: 'Quill' },
            'GET /v1/channels/ch_1': CHANNEL,
            'POST /v1/channels': { ...CHANNEL, id: 'ch_2', name: 'q4' },
        });
        const room = (await api({ 'GET /v1/channels': list(CHANNEL) }).transport.channels())[0];
        await transport.addAgent(room, { id: 'agt_2', source: 'platform', name: 'Quill' });
        expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /v1/workspaces/ws_1', 'POST /v1/workspaces/ws_1/members', 'POST /v1/channels/ch_1/members', 'GET /v1/channels/ch_1']);
        expect(calls[1].body).toEqual({ agent_id: 'agt_2' });

        calls.length = 0;
        const agents = [
            { id: 'agt_1', source: 'platform', name: 'Scout' },
            { id: 'agt_2', source: 'platform', name: 'Quill' },
        ] as const;
        await transport.createChannel({ workspaceId: 'ws_1', name: 'q4', topic: '', agents: [...agents] });
        expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /v1/workspaces/ws_1', 'POST /v1/workspaces/ws_1/members', 'POST /v1/channels']);
        expect(calls[2].body).toEqual({ name: 'q4', workspace_id: 'ws_1', members: [{ agent_id: 'agt_1' }, { agent_id: 'agt_2' }], mode: 'all' });
    });

    it("never offers one of NoClick's helpers, which it made for its own work", async () => {
        const { transport } = api({
            'GET /v1/agents': list(
                { object: 'agent', id: 'agt_1', name: 'Scout', harness: 'sdk', status: 'idle', helper: false },
                { object: 'agent', id: 'agt_2', name: 'shop-coder', harness: 'codex', status: 'idle', helper: true }
            ),
        });
        expect((await transport.agents()).map((a) => a.name)).toEqual(['Writer', 'Scout']);
    });

    it('offers the agents from elsewhere first, and puts one in a channel through MORE_AGENTS, never the API', async () => {
        const automationMember = { object: 'channel_member', id: 'mem_4', type: 'workflow_agent', name: 'Writer', agent_id: null, workflow_id: 'wf_1', node_id: 'writer', workflow_name: 'Content', busy: false };
        const withWriter = { ...CHANNEL, members: [...CHANNEL.members, automationMember] };
        const { transport, calls, more } = api({
            'GET /v1/agents': list({ object: 'agent', id: 'agt_1', name: 'Scout', harness: 'sdk', status: 'idle' }),
            'GET /v1/channels/ch_1': withWriter,
            'POST /v1/channels': { ...CHANNEL, id: 'ch_2', name: 'q4', workspace_id: null, members: [] },
            'GET /v1/channels/ch_2': { ...CHANNEL, id: 'ch_2', name: 'q4', workspace_id: null, members: [automationMember] },
        });
        const agents = await transport.agents();
        expect(agents.map((a) => [a.source, a.id, a.name, a.markType])).toEqual([
            ['automation', 'wf_1:writer', 'Writer', 'agent:claude-code'],
            ['platform', 'agt_1', 'Scout', 'agent'],
        ]);

        const room = { id: 'ch_1', workspaceId: 'ws_1' } as Channel;
        const after = await transport.addAgent(room, agents[0]);
        expect(more!.added).toEqual([['ch_1', 'wf_1:writer']]);
        // Read back through /v1, which holds it as any member: no workspace join, no /v1 member write.
        expect(calls.slice(1).map((c) => `${c.method} ${c.path}`)).toEqual(['GET /v1/channels/ch_1']);
        expect(after.members.at(-1)).toMatchObject({ kind: 'agent', name: 'Writer', workflowId: 'wf_1', nodeId: 'writer', workflowName: 'Content' });
        expect(after.members.at(-1)?.agentId).toBeUndefined();

        calls.length = 0;
        const made = await transport.createChannel({ workspaceId: null, name: 'q4', topic: '', agents: [agents[0], agents[1]] });
        expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(['POST /v1/channels', 'GET /v1/channels/ch_2']);
        expect(calls[0].body).toEqual({ name: 'q4', members: [{ agent_id: 'agt_1' }], mode: 'all' });
        expect(more!.added.at(-1)).toEqual(['ch_2', 'wf_1:writer']);
        expect(made.members.map((m) => m.name)).toEqual(['Writer']);
    });

    it("reads the message of an agent from elsewhere as its own", async () => {
        const { transport } = api({
            'GET /v1/channels/ch_1/messages': list({ ...MESSAGE, author: { type: 'workflow_agent', id: 'mem_4', name: 'Writer' }, reactions: [] }),
        });
        const [message] = (await transport.history('ch_1')).messages;
        expect(message.author).toEqual({ type: 'workflow_agent', id: 'mem_4', name: 'Writer' });
    });

    it('turns a refusal into the sentence to show, and a frame into a change', async () => {
        const { transport } = api({
            'GET /v1/workspaces': new Response(
                JSON.stringify({ error: { type: 'plan_required', message: 'The NoClick API is part of the paid plans.', next_step: 'Upgrade to Plus or Pro.' } }),
                { status: 402 }
            ),
        });
        await expect(transport.workspaces()).rejects.toThrow('The NoClick API is part of the paid plans. Upgrade to Plus or Pro.');
        expect(changeOf({ kind: 'reaction', channel_id: 'ch_1', workspace_id: null, message_id: 'm2' })).toEqual({ kind: 'reaction', channelId: 'ch_1', workspaceId: undefined, messageId: 'm2' });
        const seen: string[] = [];
        const stop = transport.subscribe((change) => seen.push(change.kind));
        transport.deliver({ kind: 'message', channelId: 'ch_1' });
        stop();
        transport.deliver({ kind: 'message', channelId: 'ch_1' });
        expect(seen).toEqual(['message']);
        expect(typingChangeOf({ channel_id: 'ch_1', workspace_id: 'ws_1', user_id: 'usr_ana', name: 'Ana', typing: true })).toEqual({
            kind: 'typing',
            channelId: 'ch_1',
            workspaceId: 'ws_1',
            typist: { id: 'usr_ana', name: 'Ana', typing: true },
        });
    });

    it('offers only the platform\'s agents where nothing adds others, and refuses one from elsewhere there', async () => {
        const { transport } = api({ 'GET /v1/agents': list({ object: 'agent', id: 'agt_1', name: 'Scout', harness: 'sdk', status: 'idle' }) }, null);
        expect((await transport.agents()).map((a) => [a.source, a.name])).toEqual([['platform', 'Scout']]);
        await expect(transport.addAgent({ id: 'ch_1', workspaceId: null } as Channel, WRITER)).rejects.toThrow('Writer can’t be added here.');
    });

    it("says you're typing through the API, and that you stopped", async () => {
        const { transport, calls } = api({ 'POST /v1/channels/ch_1/typing': () => new Response(null, { status: 204 }) });
        await transport.typing('ch_1', true);
        await transport.typing('ch_1', false);
        expect(calls.map((c) => [c.method, c.path, c.body])).toEqual([
            ['POST', '/v1/channels/ch_1/typing', { typing: true }],
            ['POST', '/v1/channels/ch_1/typing', { typing: false }],
        ]);
    });
});
