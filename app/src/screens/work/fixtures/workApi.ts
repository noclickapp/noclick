// A fake /v1 for Work: the account's spaces (its own, and one it joined in another account, reached through a
// session), their people, invites, channels and DMs with their messages, threads, pins, bookmarks and shared files,
// and its agents, kept as state the requests read and change, with a frame for each change (delivered to `live`, as
// the account's change stream delivers the platform's). The real platform client runs over it, so Work is exercised through the
// SDK as it is in the app. Tests and the local preview build on `fakeWork`.
import { workFixtureClient } from './client';
import type { NoClick } from 'noclick';
import { createWorkLive, type WorkLive } from '@/sdk/live';

type Json = Record<string, unknown>;

export interface FakeWork {
    client: NoClick;
    /** The fake's own fetch: a session's client (a joined space's) reaches it through the global fetch. */
    fetch: typeof window.fetch;
    live: WorkLive;
    /** Every request the clients sent, with the session it came as (null: the account). */
    requests: { method: string; path: string; query: URLSearchParams; body: unknown; session: string | null }[];
    workspaces: Json[];
    channels: Json[];
    /** Each channel's messages (replies too), oldest first. */
    messages: Map<string, Json[]>;
    bookmarks: Map<string, Json[]>;
    invites: Json[];
    /** Resources shared with a space, with what its members and guests get. */
    links: Json[];
    agents: Json[];
    /** What the person's own NoClick asked each space's NoClick, by space, newest first. */
    questions: Map<string, Json[]>;
    /** Each reader's own sections of a space's channels, by `sectionsKey`, as GET /v1/channels/sections answers them. */
    sections: Map<string, Json>;
    /** Someone else posts (a person, an agent), as the platform would, with its frame. */
    post(channelId: string, message: { author: Json; text: string; thread_id?: string; also_in_channel?: boolean; attachments?: Json[] }): Json;
    /** A trigger starts or continues one of an agent's conversations (a WhatsApp chat, named for whom it's with), as the
     *  platform would: it lists as the newest, and its turn's frame names it. */
    chat(agentId: string, conversation: string, title: string): void;
    /** Fail every request for `path` (a prefix), or only its `method`, with this sentence. */
    fail(path: string, message: string, method?: string): void;
    /** Stop failing `path`. */
    pass(path: string): void;
}

/** Whose sections of which space: the account's (no session) or the joined person's, and the space's workspace. */
export const sectionsKey = (session: string | null, workspaceId: string | null) => `${session ?? 'account'}:${workspaceId ?? ''}`;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const notFound = (message: string) => json({ error: { type: 'not_found', message } }, 404);
const list = (data: unknown[], next: string | null = null) => ({ object: 'list', data, next_cursor: next });

/** The signed-in person: the account's owner, and in the space they joined, that account's user. */
export const ACCOUNT = { type: 'account', id: null, name: 'Rowan Hale' };
export const ME_THERE = 'usr_me';
export const JOINED_SESSION = 'nk_sess_acme_fixture';
const agent = (id: string, name: string, role: string, harness = 'claude_code', model = 'claude-sonnet-5-5') => ({ object: 'agent', id, name, role, harness, status: 'active', model, instructions: `${role}.`, noclick: false });
export const AGENTS: Json[] = [
    agent('agt_support', 'Support', 'Answers customers and refunds within policy', 'sdk', 'openrouter/openai/gpt-luna'),
    agent('agt_growth', 'Growth', 'Writes the site and the launch copy'),
    agent('agt_wirefern', 'Wirefern', 'Keeps the WhatsApp webhooks service healthy', 'codex', 'gpt-5.6'),
];
/** The harnesses the agents run on, with their models labelled as the harnesses' own lists label them. */
const HARNESSES: Json[] = [
    { name: 'sdk', label: 'NoClick agent', default_model: 'openrouter/openai/gpt-luna', model_connection: 'optional' },
    { name: 'claude_code', label: 'Claude Code', default_model: 'claude-sonnet-5-5', model_connection: 'required' },
    { name: 'codex', label: 'Codex', default_model: 'gpt-5.6', model_connection: 'required' },
];
const MODELS: Record<string, Json[]> = {
    sdk: [{ id: 'openrouter/openai/gpt-luna', label: '[openrouter] OpenAI: GPT Luna' }],
    claude_code: [
        { id: 'claude-opus-5-5', label: 'Opus 5.5' },
        { id: 'claude-sonnet-5-5', label: 'Sonnet 5.5' },
    ],
    codex: [{ id: 'gpt-5.6', label: 'GPT-5.6' }],
};
const ACME_AGENT = agent('agt_acme_ops', 'Ops', 'Runs Acme’s deploys');
/** The account's own NoClick agent, as the platform provides it: named `coordinator`, no user's, flagged a NoClick. */
export const COORDINATOR: Json = { ...agent('agt_noclick', 'coordinator', 'Your assistant across the whole account', 'sdk'), user_id: null, noclick: true };
// A NoClick joins as "NoClick", flagged, as the platform adds one.
const member = (a: Json, i: number) => ({ object: 'channel_member', id: `mem_${String(a.id)}_${i}`, type: 'agent', agent_id: a.id, name: a.noclick ? 'NoClick' : a.name, noclick: a.noclick === true, busy: false });
const person = (id: string, name: string) => ({ object: 'channel_member', id: `mem_${id}`, type: 'user', user_id: id, name, busy: false });

const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
const MARKDOWN_LINK = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
const BARE_LINK = /(^|[^(\w])(https?:\/\/[^\s)<>]+)/g;

function seed() {
    const wsPerson = (id: string, userId: string, name: string, role: string, email: string, seen: number) => ({ id, type: 'user', user_id: userId, name, role, email, person: true, last_seen_at: at(seen), joined_at: at(3000), created_at: at(3000) });
    const workspaces: Json[] = [
        {
            object: 'workspace',
            id: 'ws_noclick',
            name: 'NoClick',
            logo_url: null,
            status: 'active',
            user_id: null,
            channel_count: 4,
            people_limit: 50,
            members: [...AGENTS.map((a, i) => ({ id: `wsm_${i}`, type: 'agent', agent_id: a.id, name: a.name, role: null })), wsPerson('wsm_priya', 'usr_priya', 'Priya Shah', 'admin', 'priya@example.com', 2)],
            // The newest of your own: the platform lists it first.
            created_at: at(8000),
        },
        { object: 'workspace', id: 'ws_wirefern', name: 'Wirefern', logo_url: null, status: 'active', user_id: null, channel_count: 1, people_limit: 50, members: [], created_at: at(9000) },
        {
            object: 'workspace',
            id: 'ws_acme',
            name: 'Acme',
            logo_url: null,
            status: 'active',
            user_id: null,
            channel_count: 1,
            people_limit: 3,
            joined: true,
            members: [{ id: 'wsm_ops', type: 'agent', agent_id: ACME_AGENT.id, name: ACME_AGENT.name, role: null }, wsPerson('wsm_me', ME_THERE, 'Rowan Hale', 'member', 'rowan@example.com', 0)],
            created_at: at(7000),
        },
    ];
    const channel = (id: string, name: string, topic: string, workspace: string, members: Json[], extra: Json = {}) => ({
        object: 'channel',
        id,
        name,
        topic,
        mode: 'all',
        status: 'open',
        halt_reason: null,
        unread_count: 0,
        user_id: null,
        workspace_id: workspace,
        kind: 'channel',
        members,
        created_at: at(7000 - id.length),
        ...extra,
    });
    const channels: Json[] = [
        channel('ch_launch', 'launch', 'Thursday’s launch of the new pricing', 'ws_noclick', [member(AGENTS[1], 0), member(AGENTS[0], 1), person('usr_priya', 'Priya Shah')]),
        channel('ch_incidents', 'incidents', 'When something breaks', 'ws_noclick', [member(AGENTS[2], 0)], { unread_count: 3, created_at: at(6900) }),
        channel('ch_seo', 'seo', 'Search and guides', 'ws_noclick', [member(AGENTS[1], 0)], { created_at: at(6800) }),
        channel('ch_hooks', 'general', 'The Wirefern service', 'ws_wirefern', [member(AGENTS[2], 0)], { created_at: at(6700) }),
        channel('dm_priya', 'priya-shah', '', 'ws_noclick', [person('usr_priya', 'Priya Shah')], { kind: 'dm', unread_count: 1, last_message: { id: 'p2', text: 'Want me to review the migration fix?', author: { type: 'user', id: 'usr_priya', name: 'Priya Shah' }, created_at: at(20) } }),
        channel('ch_acme', 'deploys', 'Acme’s releases', 'ws_acme', [member(ACME_AGENT, 0), person(ME_THERE, 'Rowan Hale')], { created_at: at(6600) }),
    ];
    const msg = (id: string, channel: string, author: Json, text: string, minutesAgo: number, extra: Json = {}): Json => ({
        object: 'channel_message',
        id,
        channel_id: channel,
        author,
        text,
        mentions: [],
        created_at: at(minutesAgo),
        attachments: [],
        reactions: [],
        reply_count: 0,
        last_reply_at: null,
        reply_authors: [],
        pinned: null,
        thread_id: null,
        also_in_channel: false,
        following: false,
        unread_replies: 0,
        ...extra,
    });
    const growth = { type: 'agent', id: 'agt_growth', name: 'Growth' };
    const priya = { type: 'user', id: 'usr_priya', name: 'Priya Shah' };
    const messages = new Map<string, Json[]>([
        [
            'ch_launch',
            [
                msg('l1', 'ch_launch', ACCOUNT, 'Let’s ship the new pricing Thursday. @Growth, can you rewrite the page around Free and Member?', 120, { mentions: ['Growth'] }),
                msg('l2', 'ch_launch', growth, 'On it. I’ll put the draft on a preview first.', 118),
                msg('l3', 'ch_launch', priya, 'Thanks. I’ll check the checkout page myself, the copy there is mine. See https://noclick.com/pricing', 100, {
                    attachments: [{ object: 'channel_attachment', id: 'att_copy', name: 'checkout-copy-v3.pdf', mime_type: 'application/pdf', size_bytes: 88_000, kind: 'file', url: 'https://files.test/checkout-copy-v3.pdf' }],
                }),
                msg('l4', 'ch_launch', growth, 'The new copy is on a [preview](https://pricing-v2.preview.noclick.app), ready for you to look at.', 60, {
                    reply_count: 2,
                    last_reply_at: at(40),
                    reply_authors: [ACCOUNT, priya],
                    following: true,
                    unread_replies: 1,
                    pinned: { by: priya, at: at(55) },
                    reactions: [{ emoji: '👀', count: 1, by: [priya] }],
                }),
                msg('l4r1', 'ch_launch', priya, 'Checkout reads right on the preview.', 45, { thread_id: 'l4' }),
                msg('l4r2', 'ch_launch', ACCOUNT, 'Great. Ship it Thursday morning with the rest.', 40, { thread_id: 'l4' }),
            ],
        ],
        ['ch_incidents', [msg('i1', 'ch_incidents', { type: 'agent', id: 'agt_wirefern', name: 'Wirefern' }, 'Retries are back to normal.', 30)]],
        ['ch_seo', []],
        ['ch_hooks', []],
        ['dm_priya', [msg('p1', 'dm_priya', ACCOUNT, 'Morning! Did you see the retries thread?', 25), msg('p2', 'dm_priya', priya, 'Want me to review the migration fix?', 20)]],
        [
            'ch_acme',
            [
                msg('a1', 'ch_acme', { type: 'account', id: null, name: 'Maya Lee' }, 'Welcome to Acme’s deploys.', 50),
                msg('a2', 'ch_acme', { type: 'user', id: ME_THERE, name: 'Rowan Hale' }, 'Thanks, glad to help.', 45),
            ],
        ],
    ]);
    const bookmarks = new Map<string, Json[]>([['ch_launch', [{ object: 'channel_bookmark', id: 'bm_1', channel_id: 'ch_launch', title: 'Pricing launch plan', url: 'https://docs.google.com/document/d/1pL9xQ/edit', by: ACCOUNT, created_at: at(200) }]]]);
    const invites: Json[] = [
        { object: 'workspace_invite', id: 'inv_link', workspace_id: 'ws_noclick', type: 'link', role: 'member', email: null, url: 'https://noclick.test/invite/tok_link', uses: 1, max_uses: null, uses_left: null, status: 'active', expires_at: at(-60 * 24 * 20), created_at: at(600) },
        { object: 'workspace_invite', id: 'inv_sam', workspace_id: 'ws_noclick', type: 'email', role: 'guest', email: 'sam@example.com', url: 'https://noclick.test/invite/tok_sam', uses: 0, max_uses: 1, uses_left: 1, status: 'active', expires_at: at(-60 * 24 * 5), created_at: at(300) },
    ];
    const links: Json[] = [
        { object: 'workspace_resource', id: 'lnk_repo', workspace_id: 'ws_noclick', kind: 'repo', ref: 'rep_site', name: 'site', members_level: 'write', guests_level: 'read', levels: ['none', 'agents', 'read', 'write'], added_by: ACCOUNT, added_at: at(900) },
        { object: 'workspace_resource', id: 'lnk_db', workspace_id: 'ws_noclick', kind: 'database', ref: 'db_orders', name: 'orders', members_level: 'agents', guests_level: 'none', levels: ['none', 'agents', 'read', 'write'], added_by: ACCOUNT, added_at: at(800) },
        { object: 'workspace_resource', id: 'lnk_plan', workspace_id: 'ws_noclick', kind: 'automation', ref: 'wf_monday_plan', name: 'Monday plan', members_level: 'run', guests_level: 'none', levels: ['none', 'agents', 'runs', 'run', 'edit'], added_by: ACCOUNT, added_at: at(700) },
        { object: 'workspace_resource', id: 'lnk_digest', workspace_id: 'ws_noclick', kind: 'automation', ref: 'wf_weekly_digest', name: 'Weekly sales digest', members_level: 'runs', guests_level: 'none', levels: ['none', 'agents', 'runs', 'run', 'edit'], added_by: ACCOUNT, added_at: at(650) },
    ];
    return { workspaces, channels, messages, bookmarks, invites, links };
}

/** `empty`: an account with nothing yet (`noclick`: but its NoClick, as a new account has). `oddNames`: each space's
 *  NoClick is made under a name unlike the platform's, so only the platform's `noclick` flag tells it. */
/** `mentions`: the platform counts what @-mentions the reader (`mention_count`) and lets a person join a channel. */
export function fakeWork(options: { empty?: boolean; noclick?: boolean; joined?: boolean; oddNames?: boolean; mentions?: boolean } = {}): FakeWork {
    const live = createWorkLive();
    const seeded = options.empty ? { workspaces: [], channels: [], messages: new Map<string, Json[]>(), bookmarks: new Map<string, Json[]>(), invites: [], links: [] } : seed();
    const { workspaces, channels, messages, bookmarks, invites, links } = seeded;
    if (options.mentions) for (const c of channels) c.mention_count = c.mention_count ?? 0;
    // The space joined in another account is listed only when asked for.
    if (options.joined === false) workspaces.splice(workspaces.findIndex((w) => w.id === 'ws_acme') >>> 0, 1);
    const agents = options.empty ? [] : [...AGENTS];
    // Listed beside the account's agents, and provided whenever it's asked for by name, an empty account's too.
    // Each space's own NoClick, made the first time it's asked for (`/v1/workspaces/{id}/noclick`), named for the space.
    const spaceNoClicks = new Map<string, Json>();
    const questions = new Map<string, Json[]>();
    const sections = new Map<string, Json>();
    const ownSpaceNoClicks = () => [...spaceNoClicks].filter(([wid]) => !workspaces.find((w) => w.id === wid)?.joined).map(([, a]) => a);
    const withNoClick = () => [...(options.empty && !options.noclick ? agents : [...agents, COORDINATOR]), ...ownSpaceNoClicks()];
    const agentById = (id: unknown) => [...agents, COORDINATOR, ...spaceNoClicks.values()].find((a) => a.id === id);
    const refusesNoClick = (workspaceId: unknown, agentIds: unknown[]) => !!workspaceId && agentIds.includes(COORDINATOR.id);
    const OWN_NOCLICK_REFUSED = json({ error: { type: 'invalid_request', message: 'This space has its own NoClick; add that one.' } }, 400);
    const requests: FakeWork['requests'] = [];
    const failing = new Map<string, { message: string; method?: string }>();
    // What's in the trash, by its trash id: a channel, or a space with its channels.
    const trash = new Map<string, { kind: 'channel' | 'workspace'; rows: Json[]; at: number }>();
    const trashed = (kind: 'channel' | 'workspace', row: Json, rows: Json[]) => {
        const tid = `trash_${++made}`;
        trash.set(tid, { kind, rows, at: kind === 'workspace' ? workspaces.indexOf(row) : channels.indexOf(row) });
        return { object: kind, id: row.id, deleted: true, trash: { object: 'trash_item', id: tid, kind, resource_id: row.id, name: row.name, trashed_at: new Date().toISOString(), purge_after: at(-60 * 24 * 30) }, restorable_until: at(-60 * 24 * 30), operation_id: null };
    };
    // As the platform previews each delete (its own words).
    const PREVIEWS: Record<string, (row: Json) => Json> = {
        channel: (c) => ({ deletes: `Moves the channel #${String(c.name)} to the trash with its messages and files, restorable for 30 days as it was.`, depends_on_it: (c.members as Json[]).filter((m) => m.type === 'agent').map((m) => `${String(m.name)} stops answering in it.`), data_lost: [], reversible: true, undo: 'Restorable from the trash for 30 days.' }),
        workspace: (w) => {
            const its = channels.filter((c) => c.workspace_id === w.id && c.kind !== 'dm');
            const people = (w.members as Json[]).filter((m) => m.type === 'user').map((m) => String(m.name).split(' ')[0]);
            return {
                deletes: `Moves the workspace ${String(w.name)} to the trash with ${its.length} channel${its.length === 1 ? '' : 's'} (${its.map((c) => `#${String(c.name)}`).join(', ')}), their messages and files, its invites, its own NoClick, restorable for 30 days as it was.`,
                depends_on_it: people.length ? [`Its people (${people.join(', ')}) lose it until it's restored.`] : [],
                data_lost: [],
                reversible: true,
                undo: 'Restorable from the trash for 30 days.',
            };
        },
    };
    let made = 0;

    // Each agent's conversations, newest first.
    const agentConversations = new Map<string, Json[]>();
    const conversationsOf = (agentId: string) => {
        if (!agentConversations.has(agentId))
            agentConversations.set(agentId, [
                { conversation: 'refunds', title: 'Refunds', last_activity: at(5), archived: false, active: true },
                { conversation: 'main', title: null, last_activity: at(90), archived: false },
            ]);
        return agentConversations.get(agentId)!;
    };
    const frame = (kind: string, fields: Json) =>
        // Delivered once the request answers, as the platform's socket frame lands after its write.
        setTimeout(() => live.deliver('platform:channel', { kind, channel_id: null, workspace_id: null, message_id: null, ...fields } as never), 0);
    const channelOf = (id: string) => channels.find((c) => c.id === id);
    const timeline = (id: string) => (messages.get(id) ?? []).filter((m) => !m.thread_id || m.also_in_channel);
    const repliesOf = (id: string, parent: string) => (messages.get(id) ?? []).filter((m) => m.thread_id === parent);
    const find = (id: string, mid: string) => messages.get(id)?.find((m) => m.id === mid);
    const page = (rows: Json[], query: URLSearchParams) => {
        const limit = Number(query.get('limit') ?? 50);
        const before = query.get('before');
        const after = query.get('after');
        if (after) {
            const i = rows.findIndex((m) => m.id === after);
            return list(rows.slice(i + 1, i + 1 + limit));
        }
        const end = before ? rows.findIndex((m) => m.id === before) : rows.length;
        const start = Math.max(0, end - limit);
        return list(rows.slice(start, end), start > 0 ? String(rows[start].id) : null);
    };
    const addMessage = (channelId: string, m: Json) => {
        const row: Json = {
            object: 'channel_message',
            id: `m${++made}`,
            channel_id: channelId,
            mentions: [],
            created_at: new Date().toISOString(),
            attachments: [],
            reactions: [],
            reply_count: 0,
            last_reply_at: null,
            reply_authors: [],
            pinned: null,
            thread_id: null,
            also_in_channel: false,
            following: false,
            unread_replies: 0,
            ...m,
        };
        messages.set(channelId, [...(messages.get(channelId) ?? []), row]);
        const parentId = row.thread_id as string | null;
        if (parentId) {
            const parent = find(channelId, parentId);
            if (parent) {
                parent.reply_count = Number(parent.reply_count) + 1;
                parent.last_reply_at = row.created_at;
                const author = row.author as Json;
                parent.reply_authors = [author, ...(parent.reply_authors as Json[]).filter((a) => a.id !== author.id || a.type !== author.type)].slice(0, 5);
                if (author.type !== 'account') parent.unread_replies = Number(parent.unread_replies) + (parent.following ? 1 : 0);
                else parent.following = true;
            }
            frame('thread', { channel_id: channelId, thread_id: parentId, message_id: row.id });
            if (row.also_in_channel) frame('message', { channel_id: channelId });
        } else frame('message', { channel_id: channelId });
        return row;
    };
    /** The channel's record of who joined or left, as the platform keeps it: NoClick's system message, waking no one. */
    const recordMembership = (channelId: string, action: 'added' | 'removed', by: Json | null, joined: Json[]) => {
        const names = joined.map((m) => String(m.name)).join(' and ');
        addMessage(channelId, {
            author: { type: 'system', id: null, name: 'NoClick' },
            text: by ? `${String(by.name)} ${action} ${names}.` : `${names} ${action === 'added' ? 'joined' : 'left'}.`,
            event: { type: 'membership', action, by, members: joined.map((m) => ({ id: m.id, type: m.type, name: m.name, agent_id: m.agent_id ?? null, user_id: m.user_id ?? null })) },
        });
    };
    const workspaceView = (w: Json, session: string | null) => {
        const people = (w.members as Json[]).filter((m) => m.type === 'user');
        return { ...w, role: session ? 'member' : 'owner', people_count: people.length };
    };
    const linksOf = (m: Json) => {
        const text = String(m.text ?? '');
        const marked = [...text.matchAll(MARKDOWN_LINK)].map((x) => ({ url: x[2], title: x[1] }));
        const bare = [...text.replace(MARKDOWN_LINK, '').matchAll(BARE_LINK)].map((x) => ({ url: x[2].replace(/[.,;:!?]+$/, ''), title: null }));
        return [...marked, ...bare].map((l) => ({ ...l, domain: new URL(l.url).hostname }));
    };
    const shared = (id: string, query: URLSearchParams, kind: 'files' | 'links') => {
        const q = (query.get('q') ?? '').toLowerCase();
        const rows = [...(messages.get(id) ?? [])].reverse().flatMap((m): Json[] => {
            const base = { message_id: m.id, thread_id: m.thread_id, author: m.author, created_at: m.created_at };
            return kind === 'files' ? (m.attachments as Json[]).map((file) => ({ ...base, file })) : linksOf(m).map((l) => ({ ...base, ...l }));
        });
        return list(rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q)));
    };

    const routes = (method: string, path: string, query: URLSearchParams, body: unknown, session: string | null): Response => {
        // A refusal, so the client doesn't retry it.
        for (const [prefix, f] of failing) if (path.startsWith(prefix) && (!f.method || f.method === method)) return json({ error: { type: 'invalid_request', message: f.message } }, 400);
        const b = (body ?? {}) as Json;
        // A session reaches only the space it was minted for.
        const visible = (w: Json) => (session ? w.id === 'ws_acme' : !w.joined);
        if (method === 'GET' && path === '/v1/me/workspaces') {
            // As the platform lists them: your own active ones (newest first), the active ones you joined, then your own
            // archived ones (newest first). Someone else's archived space isn't listed.
            const newest = (x: Json, y: Json) => String(y.created_at).localeCompare(String(x.created_at));
            // Your personal space's, once you've shared it, is last of your own active ones.
            const own = workspaces.filter((w) => !w.joined && !w.personal).sort(newest);
            const view = (w: Json) =>
                w.joined
                    ? { object: 'my_workspace', id: w.id, name: w.name, logo_url: w.logo_url, own: false, role: 'member', account_name: 'Maya Lee', user_id: ME_THERE, member_id: 'wsm_me', joined_at: at(3000), status: w.status, personal: false }
                    : { object: 'my_workspace', id: w.id, name: w.name, logo_url: w.logo_url, own: true, role: 'owner', account_name: null, user_id: null, member_id: null, joined_at: null, status: w.status, personal: !!w.personal };
            const personal = workspaces.filter((w) => w.personal);
            return json(list([...own.filter((w) => w.status === 'active'), ...personal, ...workspaces.filter((w) => w.joined && w.status === 'active'), ...own.filter((w) => w.status === 'archived')].map(view)));
        }
        // Your personal space as a space people can join: its workspace, made the first time.
        if (method === 'POST' && path === '/v1/me/personal_space') {
            let w = workspaces.find((x) => x.personal);
            if (!w) {
                w = { object: 'workspace', id: `ws_personal_${++made}`, name: 'Rowan’s space', logo_url: null, status: 'active', user_id: null, channel_count: 0, people_limit: 3, members: [], personal: true, created_at: new Date().toISOString() };
                workspaces.push(w);
                frame('workspace', { workspace_id: w.id });
            }
            return json({ object: 'my_workspace', id: w.id, name: w.name, logo_url: null, own: true, role: 'owner', account_name: null, user_id: null, member_id: null, joined_at: null, status: 'active', personal: true });
        }
        const mine = path.match(/^\/v1\/me\/workspaces\/([^/]+)(\/sessions)?$/);
        if (mine) {
            if (method === 'POST' && mine[2]) return json({ object: 'session', id: 'ses_1', token: JOINED_SESSION, user_id: ME_THERE, scopes: ['agents', 'channels'], expires_at: at(-60), workspace_id: mine[1] }, 201);
            if (method === 'DELETE') {
                workspaces.splice(workspaces.findIndex((w) => w.id === mine[1]), 1);
                frame('workspace', { workspace_id: mine[1] });
                return new Response(null, { status: 204 });
            }
        }
        if (method === 'POST' && path === '/v1/delete_previews') {
            const [, kind, rid] = String(b.path).match(/^\/v1\/(channels|workspaces)\/([^/]+)$/) ?? [];
            const row = kind === 'channels' ? channelOf(rid) : workspaces.find((w) => w.id === rid);
            if (!row) return notFound('Nothing there to preview.');
            return json({ object: 'delete_preview', impact: PREVIEWS[kind === 'channels' ? 'channel' : 'workspace'](row) });
        }
        const restoring = path.match(/^\/v1\/trash\/([^/]+)\/restore$/);
        if (restoring && method === 'POST') {
            const held = trash.get(restoring[1]);
            if (!held) return notFound('Nothing in the trash with that id.');
            trash.delete(restoring[1]);
            const [row, ...rest] = held.rows;
            if (held.kind === 'workspace') workspaces.splice(held.at, 0, row);
            else channels.splice(held.at, 0, row);
            channels.push(...rest);
            frame(held.kind === 'workspace' ? 'workspace' : 'channel', held.kind === 'workspace' ? { workspace_id: row.id } : { channel_id: row.id, workspace_id: row.workspace_id });
            return json({ ...row, restored: true });
        }
        if (method === 'GET' && path === '/v1/workspaces') return json(list(workspaces.filter((w) => visible(w) && !w.personal && (!query.get('status') || w.status === query.get('status')))));
        if (method === 'POST' && path === '/v1/workspaces') {
            const w = { object: 'workspace', id: `ws_${++made}`, name: b.name, logo_url: null, status: 'active', user_id: null, channel_count: 0, people_limit: 50, members: [], created_at: new Date().toISOString() };
            workspaces.push(w);
            frame('workspace', { workspace_id: w.id });
            return json(workspaceView(w, session), 201);
        }
        const ws = path.match(/^\/v1\/workspaces\/([^/]+)(\/.*)?$/);
        if (ws) {
            const [, wid, sub = ''] = ws;
            const w = workspaces.find((x) => x.id === wid && visible(x));
            if (!w) return notFound(`No workspace ${wid}.`);
            const changed = (status = 200, out: unknown = workspaceView(w, session)) => {
                frame('workspace', { workspace_id: wid });
                return json(out, status);
            };
            if (sub === '' && method === 'GET') return json(workspaceView(w, session));
            if (sub === '/questions' && method === 'GET') return json(list(questions.get(wid) ?? []));
            if (sub === '/noclick' && method === 'GET') {
                let own = spaceNoClicks.get(wid);
                if (!own) {
                    const hex = Array.from(wid, (ch) => ch.charCodeAt(0).toString(16).padStart(2, '0')).join('').padEnd(32, '0').slice(0, 32);
                    own = { ...agent(`agt_nc_${wid}`, options.oddNames ? `space-helper-${wid}` : `noclick-${hex}`, 'This space’s NoClick: changes the space when asked', 'sdk', 'openrouter/openai/gpt-luna'), user_id: null, noclick: true };
                    spaceNoClicks.set(wid, own);
                    (w.members as Json[]).push({ id: `wsm_nc_${wid}`, type: 'agent', agent_id: own.id, name: own.name, noclick: true, role: null });
                }
                return json({ object: 'workspace_noclick', workspace_id: wid, agent_id: own.id, name: own.name, label: `NoClick · ${String(w.name)}` });
            }
            if (sub === '' && method === 'PATCH') return changed(200, workspaceView(Object.assign(w, b.name ? { name: b.name } : {}), session));
            // Archiving closes its open channels, which unarchiving opens again.
            if (sub === '/archive' && method === 'POST') {
                w.status = 'archived';
                for (const c of channels.filter((x) => x.workspace_id === wid && x.status !== 'closed')) Object.assign(c, { status: 'closed', closed_with_workspace: true });
                return changed();
            }
            if (sub === '/unarchive' && method === 'POST') {
                if (workspaces.some((x) => x !== w && x.status === 'active' && x.name === w.name)) return json({ error: { type: 'conflict', message: `A workspace named '${String(w.name)}' is active already.` } }, 409);
                w.status = 'active';
                for (const c of channels.filter((x) => x.workspace_id === wid && x.closed_with_workspace)) Object.assign(c, { status: 'open', closed_with_workspace: false });
                return changed();
            }
            if (sub === '' && method === 'DELETE') {
                const its = channels.filter((c) => c.workspace_id === wid);
                const out = trashed('workspace', w, [w, ...its]);
                workspaces.splice(workspaces.indexOf(w), 1);
                for (const c of its) channels.splice(channels.indexOf(c), 1);
                return changed(200, out);
            }
            if (sub === '/logo' && method === 'PUT') return changed(200, workspaceView(Object.assign(w, { logo_url: `https://files.test/${wid}/logo` }), session));
            if (sub === '/members' && method === 'POST') {
                const a = agentById(b.agent_id);
                // Each agent joins once, as the platform has it.
                if ((w.members as Json[]).some((x) => x.agent_id === b.agent_id)) return json({ error: { type: 'conflict', message: `The agent '${a?.name}' is already a member.` } }, 409);
                const m = { id: `wsm_${++made}`, type: 'agent', agent_id: b.agent_id, name: a?.name ?? 'agent', role: null };
                (w.members as Json[]).push(m);
                return changed(201, m);
            }
            const one = sub.match(/^\/members\/([^/]+)$/);
            if (one) {
                const m = (w.members as Json[]).find((x) => x.id === decodeURIComponent(one[1]));
                if (!m) return notFound('No such member.');
                if (method === 'PATCH') return changed(200, Object.assign(m, { role: b.role }));
                if (method === 'DELETE') {
                    w.members = (w.members as Json[]).filter((x) => x !== m);
                    return changed(204, null);
                }
            }
            if (sub === '/invite_links' && method === 'POST') {
                const inv = { object: 'workspace_invite', id: `inv_${++made}`, workspace_id: wid, type: 'link', role: b.role ?? 'member', email: null, url: `https://noclick.test/invite/tok_${made}`, uses: 0, max_uses: null, uses_left: null, status: 'active', expires_at: at(-60 * 24 * 30), created_at: new Date().toISOString() };
                invites.push(inv);
                return changed(201, inv);
            }
            if (sub === '/invites' && method === 'POST') {
                const inv = { object: 'workspace_invite', id: `inv_${++made}`, workspace_id: wid, type: 'email', role: b.role ?? 'member', email: b.email, url: `https://noclick.test/invite/tok_${made}`, uses: 0, max_uses: 1, uses_left: 1, status: 'active', expires_at: at(-60 * 24 * 7), created_at: new Date().toISOString() };
                invites.push(inv);
                return changed(201, inv);
            }
            if (sub === '/invites' && method === 'GET') return json(list(invites.filter((i) => i.workspace_id === wid && (!query.get('status') || i.status === query.get('status')))));
            const inv = sub.match(/^\/invites\/([^/]+)(\/resend|\/rotate)?$/);
            if (inv) {
                const i = invites.find((x) => x.id === inv[1]);
                if (!i) return notFound('No such invite.');
                if (method === 'DELETE') return changed(200, Object.assign(i, { status: 'revoked' }));
                if (inv[2] === '/resend') return changed(200, Object.assign(i, { expires_at: at(-60 * 24 * 7) }));
            }
            if (sub === '/resources' && method === 'GET') return json(list(links.filter((l) => l.workspace_id === wid)));
            // What the space has, by kind, as its Resources tab reads it: its agents, its channels and what's shared with it.
            if (sub === '/summary' && method === 'GET') {
                const here = (w.members as Json[]).filter((m) => m.type === 'agent').map((m) => agentById(m.agent_id)).filter((a): a is Json => !!a);
                const item = (id: unknown, ref: unknown, name: unknown, link?: Json) => ({ id, ref, name, linked: !!link, members_level: link?.members_level ?? null, guests_level: link?.guests_level ?? null, used_by: here.map((a) => a.id) });
                const linked = (kind: string) => links.filter((l) => l.workspace_id === wid && l.kind === kind).map((l) => item(l.id, l.ref, l.name, l));
                const empty = { items: [] };
                return json({
                    object: 'workspace_summary',
                    workspace_id: wid,
                    kinds: {
                        agents: { count: here.length, working: 0, waiting: 0, idle: here.length, items: here.map((a) => ({ id: a.id, name: a.name, state: 'idle', harness: a.harness, model: a.model })) },
                        machines: { count: 0, up: 0, items: [] },
                        channels: { items: channels.filter((c) => c.workspace_id === wid && c.kind !== 'dm').map((c) => item(c.id, c.id, c.name)) },
                        code: { items: linked('repo') },
                        databases: { items: linked('database') },
                        // Each automation's last run and its next, as the account reads them.
                        automations: {
                            items: linked('automation').map((i) => ({
                                ...i,
                                level: 'edit',
                                used_by: [],
                                ...(i.ref === 'wf_monday_plan'
                                    ? { last_run: { id: 'run_plan', status: 'failed', at: at(60 * 24 * 4), error: 'Instagram isn’t connected' }, next_run: at(-60 * 24 * 3) }
                                    : { last_run: { id: 'run_digest', status: 'succeeded', at: at(60 * 20), error: null }, next_run: at(-60 * 28) }),
                            })),
                        },
                        ...Object.fromEntries(['skills', 'memories', 'connections', 'websites', 'files', 'numbers', 'email'].map((k) => [k, empty])),
                    },
                });
            }
            const link = sub.match(/^\/resources\/([^/]+)$/);
            if (link && method === 'PATCH') {
                const l = links.find((x) => x.id === link[1] && x.workspace_id === wid);
                if (!l) return notFound('No such resource here.');
                Object.assign(l, b.members_level ? { members_level: b.members_level } : {}, b.guests_level ? { guests_level: b.guests_level } : {});
                return json(l);
            }
            return notFound(`No route for ${method} ${path}`);
        }
        if (method === 'GET' && path === '/v1/agents' && query.get('name') === 'coordinator' && !session) return json(list([COORDINATOR]));
        if (method === 'GET' && path === '/v1/agents') return json(list(session ? [ACME_AGENT] : withNoClick()));
        if (method === 'GET' && path === '/v1/harnesses') return json(list(HARNESSES));
        const models = path.match(/^\/v1\/harnesses\/([^/]+)\/models$/);
        if (models && method === 'GET') {
            const q = query.get('q')?.toLowerCase();
            return json(list((MODELS[models[1]] ?? []).filter((m) => !q || String(m.id).includes(q)).map((m) => ({ object: 'harness_model', canonical: m.id, route: 'maker', ...m }))));
        }
        if (method === 'GET' && path === '/v1/agents/states') {
            // A person reads one space's agents at a time, the ones they reach there, never by their activity.
            if (session && !query.get('workspace_id')) return json({ error: { type: 'invalid_request', message: 'Name the space whose agents to read.', field: 'workspace_id' } }, 400);
            return json({
                object: 'list',
                data: (session ? [ACME_AGENT] : withNoClick()).map((a) => ({ agent_id: a.id, name: a.name, noclick: a.noclick === true, harness: a.harness, state: a.id === 'agt_support' ? 'needs_you' : 'idle', waiting: { total: a.id === 'agt_support' ? 2 : 0 }, last_active_at: at(60) })),
                read_at: new Date().toISOString(),
            });
        }
        const oneAgent = path.match(/^\/v1\/agents\/([^/]+)$/);
        if (method === 'GET' && oneAgent) {
            const a = [...agents, COORDINATOR, ACME_AGENT].find((x) => x.id === oneAgent[1]);
            return a ? json(a) : notFound(`No agent ${oneAgent[1]}.`);
        }
        const conversations = path.match(/^\/v1\/agents\/([^/]+)\/conversations$/);
        if (method === 'GET' && conversations) return json(list(conversationsOf(conversations[1])));
        const inSession = (c: Json) => (session ? c.workspace_id === 'ws_acme' : c.workspace_id !== 'ws_acme');
        if (path === '/v1/channels/sections') {
            const ws = (method === 'GET' ? query.get('workspace_id') : (b.workspace_id as string | null)) ?? null;
            const key = sectionsKey(session, ws);
            const kept = sections.get(key) ?? { object: 'channel_sections', workspace_id: ws, version: 0, sections: [], folded: [], updated_at: null };
            if (method === 'GET') return json(kept);
            if (method !== 'PUT') return notFound(`No route for ${method} ${path}`);
            if (b.version !== kept.version) return json({ error: { type: 'conflict', message: 'Your sections changed since this copy was read.', version: kept.version } }, 409);
            const saved = { ...kept, version: Number(kept.version) + 1, sections: b.sections ?? [], folded: b.folded ?? [], updated_at: new Date().toISOString() };
            sections.set(key, saved);
            frame('sections', { workspace_id: ws });
            return json(saved);
        }
        if (method === 'GET' && path === '/v1/channels/threads') {
            const ws = query.get('workspace_id');
            const rows = channels
                .filter((c) => inSession(c) && (!ws || c.workspace_id === ws))
                .flatMap((c) =>
                    (messages.get(String(c.id)) ?? [])
                        .filter((m) => m.following && Number(m.reply_count) > 0)
                        .map((m) => ({ object: 'channel_thread', id: m.id, channel_id: c.id, channel_name: c.name, workspace_id: c.workspace_id, parent: m, latest_reply: repliesOf(String(c.id), String(m.id)).at(-1) ?? null, reply_count: m.reply_count, unread_count: m.unread_replies, following: true, last_reply_at: m.last_reply_at }))
                );
            return json(list(rows));
        }
        if (method === 'GET' && path === '/v1/channels') {
            const ws = query.get('workspace_id');
            const kind = query.get('kind');
            const agent = query.get('agent_id');
            return json(
                list(
                    channels.filter(
                        (c) =>
                            inSession(c) &&
                            (!query.get('status') || c.status === query.get('status')) &&
                            (!ws || c.workspace_id === ws) &&
                            (!kind || c.kind === kind) &&
                            (!agent || (c.members as Json[]).some((m) => m.agent_id === agent))
                    )
                )
            );
        }
        if (method === 'POST' && path === '/v1/channels') {
            if (b.kind === 'dm') {
                const withWhom = ((b.members as Json[])[0] ?? {}).user_id as string;
                const existing = channels.find((c) => c.kind === 'dm' && c.workspace_id === b.workspace_id && (c.members as Json[]).some((m) => m.user_id === withWhom));
                if (existing) return json(existing);
                const space = workspaces.find((w) => w.id === b.workspace_id);
                const them = (space?.members as Json[] | undefined)?.find((m) => m.user_id === withWhom);
                const dm = { object: 'channel', id: `dm_${++made}`, name: 'dm', topic: '', mode: 'mentions', status: 'open', halt_reason: null, unread_count: 0, user_id: null, workspace_id: b.workspace_id, kind: 'dm', members: [person(withWhom, String(them?.name ?? 'Someone'))], last_message: null, created_at: new Date().toISOString() };
                channels.push(dm);
                messages.set(dm.id, []);
                frame('channel', { channel_id: dm.id, workspace_id: dm.workspace_id });
                return json(dm, 201);
            }
            if (refusesNoClick(b.workspace_id, ((b.members as Json[] | undefined) ?? []).map((m) => m.agent_id))) return OWN_NOCLICK_REFUSED;
            const c = {
                object: 'channel',
                id: `ch_${++made}`,
                name: b.name,
                topic: b.topic ?? '',
                mode: b.mode ?? 'all',
                status: 'open',
                halt_reason: null,
                unread_count: 0,
                user_id: null,
                workspace_id: b.workspace_id ?? null,
                kind: 'channel',
                // A space's people join by their user ids, its agents by theirs.
                members: ((b.members as Json[] | undefined) ?? []).map((m, i) => {
                    if (!m.user_id) return member(agentById(m.agent_id) ?? { id: m.agent_id, name: 'agent' }, i);
                    const them = (workspaces.find((w) => w.id === b.workspace_id)?.members as Json[] | undefined)?.find((x) => x.user_id === m.user_id);
                    return person(String(m.user_id), String(them?.name ?? 'Someone'));
                }),
                created_at: new Date().toISOString(),
            };
            channels.push(c);
            messages.set(String(c.id), []);
            if ((c.members as Json[]).length) recordMembership(String(c.id), 'added', session ? { type: 'user', id: ME_THERE, name: 'Rowan Hale' } : ACCOUNT, c.members as Json[]);
            frame('channel', { channel_id: c.id, workspace_id: c.workspace_id });
            return json(c, 201);
        }
        const ch = path.match(/^\/v1\/channels\/([^/]+)(\/.*)?$/);
        if (!ch) return notFound(`No route for ${method} ${path}`);
        const [, id, rest = ''] = ch;
        const c = channelOf(id);
        if (!c || !inSession(c)) return notFound(`No channel ${id}.`);
        const me = session ? { type: 'user', id: ME_THERE, name: 'Rowan Hale' } : ACCOUNT;
        if (rest === '' && method === 'GET') return json(c);
        const leaving = rest.match(/^\/members\/([^/]+)$/);
        if (leaving && method === 'DELETE') {
            const m = (c.members as Json[]).find((x) => x.id === decodeURIComponent(leaving[1]));
            if (!m) return notFound('No such member.');
            c.members = (c.members as Json[]).filter((x) => x !== m);
            recordMembership(id, 'removed', me, [m]);
            frame('channel', { channel_id: id, workspace_id: c.workspace_id });
            return new Response(null, { status: 204 });
        }
        if (rest === '/members' && method === 'POST') {
            if (refusesNoClick(c.workspace_id, [b.agent_id])) return OWN_NOCLICK_REFUSED;
            if ((c.members as Json[]).some((m) => m.agent_id === b.agent_id)) return json({ error: { type: 'conflict', message: 'Already a member.' } }, 409);
            const m = member(agentById(b.agent_id) ?? { id: b.agent_id, name: 'agent' }, (c.members as Json[]).length);
            (c.members as Json[]).push(m);
            recordMembership(id, 'added', me, [m]);
            frame('channel', { channel_id: id, workspace_id: c.workspace_id });
            return json(m, 201);
        }
        if (rest === '' && method === 'PATCH') {
            Object.assign(c, b);
            frame('channel', { channel_id: id });
            return json(c);
        }
        if (rest === '/close' && method === 'POST') {
            c.status = 'closed';
            frame('channel', { channel_id: id });
            return json(c);
        }
        if (rest === '/reopen' && method === 'POST') {
            const name = String(b.name ?? c.name);
            if (channels.some((x) => x !== c && x.kind !== 'dm' && x.status !== 'closed' && x.workspace_id === c.workspace_id && x.name === name))
                return json({ error: { type: 'conflict', message: `An open channel here is called #${name} already.` } }, 409);
            Object.assign(c, { status: 'open', name });
            addMessage(id, { author: { type: 'system', id: null, name: 'NoClick' }, text: 'The channel was reopened.' });
            frame('channel', { channel_id: id, workspace_id: c.workspace_id });
            return json(c);
        }
        if (rest === '' && method === 'DELETE') {
            const out = trashed('channel', c, [c]);
            channels.splice(channels.indexOf(c), 1);
            frame('channel', { channel_id: id, workspace_id: c.workspace_id });
            return json(out);
        }
        // Yours alone: a muted channel is never unread for you.
        const preference = rest.match(/^\/(star|mute)$/);
        if (preference && (method === 'POST' || method === 'DELETE')) {
            if (session && !(c.members as Json[]).some((m) => m.user_id === ME_THERE))
                return json({ error: { type: 'invalid_request', message: `You're not in this channel, so you can't ${preference[1]} it. Post in it to join it first.` } }, 400);
            Object.assign(c, preference[1] === 'star' ? { starred: method === 'POST' } : { muted: method === 'POST', ...(method === 'POST' ? { unread_count: Number(c.mention_count ?? 0) } : {}) });
            return json(c);
        }
        if (rest === '/join' && method === 'POST' && options.mentions) {
            if (!session) return json({ error: { type: 'invalid_request', message: 'Only a person in a workspace joins its channels: the account reads every one of its own.' } }, 400);
            if (c.status === 'closed') return json({ error: { type: 'conflict', message: 'The channel is closed.' } }, 409);
            if (!(c.members as Json[]).some((m) => m.user_id === ME_THERE)) {
                const m = person(ME_THERE, 'Rowan Hale');
                (c.members as Json[]).push(m);
                recordMembership(id, 'added', null, [m]);
                frame('channel', { channel_id: id, workspace_id: c.workspace_id });
            }
            return json(c);
        }
        if (rest === '/leave' && method === 'POST') {
            if (!session) return json({ error: { type: 'invalid_request', message: 'Only a person in a workspace leaves its channels: the account reads every one of its own.' } }, 400);
            const m = (c.members as Json[]).find((x) => x.user_id === ME_THERE);
            if (!m) return notFound("You're not in this channel.");
            c.members = (c.members as Json[]).filter((x) => x !== m);
            Object.assign(c, { starred: false, muted: false });
            recordMembership(id, 'removed', null, [m]);
            frame('channel', { channel_id: id, workspace_id: c.workspace_id });
            return json({ object: 'channel_membership', action: 'removed' });
        }
        if (rest === '/read' && method === 'POST') {
            c.unread_count = 0;
            if (c.mention_count !== undefined) c.mention_count = 0;
            return json(c);
        }
        if (rest === '/triggers' && method === 'GET') return json(list([]));
        // Saying you're typing keeps nothing; the fake has no other reader's page to tell.
        if (rest === '/typing' && method === 'POST') return new Response(null, { status: 204 });
        if (rest === '/attachments' && method === 'POST') {
            const name = query.get('name') ?? 'file';
            const mime = query.get('mime_type') ?? 'application/octet-stream';
            return json({ object: 'channel_attachment', id: `att_${++made}`, name, mime_type: mime, size_bytes: 12, kind: mime.startsWith('image/') ? 'image' : 'file', url: `https://files.test/${name}`, voice: query.get('voice') === 'true' }, 201);
        }
        if (rest === '/messages' && method === 'GET') return json(page(timeline(id), query));
        if (rest === '/messages' && method === 'POST') {
            const files = ((b.attachments as string[] | undefined) ?? []).map((f) => ({ object: 'channel_attachment', id: f, name: f, mime_type: 'application/pdf', size_bytes: 12, kind: 'file', url: `https://files.test/${f}` }));
            return json(addMessage(id, { author: me, text: b.text ?? '', attachments: files, thread_id: b.thread_id ?? null, also_in_channel: b.also_in_channel === true }), 201);
        }
        if (rest === '/pins' && method === 'GET') {
            const rows = (messages.get(id) ?? []).filter((m) => m.pinned).map((m) => ({ message: m, by: (m.pinned as Json).by, at: (m.pinned as Json).at }));
            return json(list(rows.reverse()));
        }
        if (rest === '/bookmarks' && method === 'GET') return json(list(bookmarks.get(id) ?? []));
        if (rest === '/bookmarks' && method === 'POST') {
            const bm = { object: 'channel_bookmark', id: `bm_${++made}`, channel_id: id, title: b.title ?? new URL(String(b.url)).hostname, url: b.url, by: me, created_at: new Date().toISOString() };
            bookmarks.set(id, [...(bookmarks.get(id) ?? []), bm]);
            frame('bookmark', { channel_id: id });
            return json(bm, 201);
        }
        const bookmark = rest.match(/^\/bookmarks\/([^/]+)$/);
        if (bookmark && method === 'DELETE') {
            bookmarks.set(id, (bookmarks.get(id) ?? []).filter((x) => x.id !== bookmark[1]));
            frame('bookmark', { channel_id: id });
            return new Response(null, { status: 204 });
        }
        if (rest === '/files' && method === 'GET') return json(shared(id, query, 'files'));
        if (rest === '/links' && method === 'GET') return json(shared(id, query, 'links'));
        const one = rest.match(/^\/messages\/([^/]+)(\/.*)?$/);
        if (one) {
            const [, mid, sub = ''] = one;
            const m = find(id, mid);
            if (!m) return notFound(`No message ${mid}.`);
            if (sub === '' && method === 'GET') return json(m);
            if (sub === '/replies' && method === 'GET') return json(page(repliesOf(id, mid), query));
            if (sub === '/read' && method === 'POST') {
                m.unread_replies = 0;
                frame('thread', { channel_id: id, thread_id: mid, message_id: null });
                return json(m);
            }
            if (sub === '/pin') {
                if (method === 'POST') {
                    // As the platform writes it: the account acts under its own name, "owner".
                    const by = me.type === 'account' ? { ...me, name: 'owner' } : me;
                    m.pinned = { by, at: new Date().toISOString() };
                    addMessage(id, { author: { type: 'system', id: null, name: 'NoClick' }, text: `${by.name} pinned a message to this channel.`, event: { type: 'pinned', message_id: mid } });
                } else m.pinned = null;
                frame('pin', { channel_id: id, message_id: mid });
                return json(m);
            }
            if (sub === '/reactions' && method === 'POST') {
                const reactions = m.reactions as Json[];
                const found = reactions.find((r) => r.emoji === b.emoji);
                if (found) {
                    found.count = Number(found.count) + 1;
                    found.by = [...(found.by as Json[]), me];
                } else reactions.push({ emoji: b.emoji, count: 1, by: [me] });
                frame('reaction', { channel_id: id, message_id: mid, thread_id: m.thread_id });
                return json(m);
            }
            const unreact = sub.match(/^\/reactions\/(.+)$/);
            if (unreact && method === 'DELETE') {
                const emoji = decodeURIComponent(unreact[1]);
                m.reactions = (m.reactions as Json[]).flatMap((r) => (r.emoji !== emoji ? [r] : Number(r.count) > 1 ? [{ ...r, count: Number(r.count) - 1, by: (r.by as Json[]).filter((x) => x.type !== me.type || x.id !== me.id) }] : []));
                frame('reaction', { channel_id: id, message_id: mid, thread_id: m.thread_id });
                return json(m);
            }
        }
        return notFound(`No route for ${method} ${path}`);
    };

    const fetch: typeof window.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const raw = init?.body;
        const body = typeof raw === 'string' ? JSON.parse(raw) : raw;
        const auth = new Headers(init?.headers).get('Authorization') ?? '';
        const session = auth.includes('nk_sess_') ? auth.replace(/^Bearer\s+/, '') : null;
        requests.push({ method, path: url.pathname, query: url.searchParams, body, session });
        return routes(method, url.pathname, url.searchParams, body, session);
    };

    return {
        client: workFixtureClient(fetch),
        fetch,
        live,
        requests,
        workspaces,
        channels,
        messages,
        bookmarks,
        invites,
        links,
        agents,
        questions,
        sections,
        post: (channelId, m) => addMessage(channelId, { ...m, thread_id: m.thread_id ?? null, also_in_channel: m.also_in_channel ?? false, attachments: m.attachments ?? [] }),
        chat: (agentId, conversation, title) => {
            const rows = conversationsOf(agentId);
            const earlier = rows.findIndex((c) => c.conversation === conversation);
            if (earlier >= 0) rows.splice(earlier, 1);
            rows.unshift({ conversation, title, last_activity: new Date().toISOString(), archived: false });
            setTimeout(() => live.deliver('platform:agent', { agent_id: agentId, change: 'turn', conversation }), 0);
        },
        fail: (path, message, method) => void failing.set(path, { message, method }),
        pass: (path) => void failing.delete(path),
    };
}
