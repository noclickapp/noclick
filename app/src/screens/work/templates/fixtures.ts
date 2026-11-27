// A space template's routes as the platform answers them, for the page of asks' tests and Work's lab: the Social media
// team (three agents, three channels, a skill, a memory, an automation and an app), its dry run for a new space and
// for a space you have, and its add, which makes the space and its #noclick welcome post in the spaces' fixture and
// says so over the live stream.
import { galleryRoutes } from '@/screens/templates/fixtures';
import type { FakeWork } from '../fixtures/workApi';

type Json = Record<string, unknown>;

export const TEMPLATE_ADDRESS = 'https://api.noclick.com/v1/public/git/3f2a1b0c-9d8e-4f7a-8b6c-5d4e3f2a1b0c.git';
export const TEMPLATE_OPERATION = 'op_template_add';
export const SOCIAL_SPACE = 'ws_social';
export const SOCIAL_NOCLICK = 'ch_social_noclick';
/** The welcome post's connect links, by their token: each one's account (named as the canvas names its app) and what
 *  it's for. */
export const TEMPLATE_LINKS: Record<string, { integration: string; label: string; credentialType: string; reason: string }> = {
    op_link_canva: { integration: 'canva', label: 'Canva', credentialType: 'canva_mcp', reason: 'For Designer' },
    op_link_instagram: { integration: 'instagram', label: 'Instagram', credentialType: 'instagram_login', reason: 'For Scheduler and Monday plan' },
    op_link_twitter: { integration: 'twitter', label: 'X', credentialType: 'twitter_oauth', reason: 'For Scheduler' },
};
/** The secret the welcome post asks for: made empty by the add and read by Designer. */
export const TEMPLATE_SECRET = 'sec_social_unsplash';

const PARTS = (into: boolean): Json[] => {
    const writer = into ? 'Social Writer' : 'Writer';
    const named = (name: string) => (into ? `social-${name}` : name);
    return [
        { kind: 'agent', name: 'Writer', as: writer, line: 'Plans and drafts posts in the brand’s voice', needs: [], included: true },
        { kind: 'agent', name: 'Designer', as: 'Designer', line: 'Makes the images', needs: ['canva'], included: true },
        { kind: 'agent', name: 'Scheduler', as: 'Scheduler', line: 'Posts at the best times', needs: ['instagram', 'linkedin', 'twitter'], included: true },
        { kind: 'channel', name: 'ideas', as: named('ideas'), line: 'Where Writer plans the week’s posts.', members: [writer], schedules: ['Plan this week’s posts from last week’s results.'], included: true },
        { kind: 'channel', name: 'drafts', as: named('drafts'), line: 'Drafts and their images.', members: [writer, 'Designer'], schedules: [], included: true },
        { kind: 'channel', name: 'scheduled', as: named('scheduled'), line: 'What goes out, and how it did.', members: ['Scheduler'], schedules: [], included: true },
        { kind: 'skill', name: 'brand-voice', as: 'brand-voice', line: `Read by ${writer}`, included: true },
        { kind: 'memory', name: 'brand', as: 'brand', line: 'What the brand sounds like', included: true },
        { kind: 'automation', name: 'Monday plan', as: 'Monday plan', line: 'Last week’s posts into #ideas', needs: ['instagram'], included: true },
        { kind: 'app', name: 'content-calendar', as: 'content-calendar', line: 'An app, its code copied into a repo of yours and deployed', included: true },
    ];
};

/** The dry run, as `POST /v1/workspaces/from_template` (`into` null) or `.../{into}/template/add` answers it. */
export function templatePlan(into: { id: string; name: string } | null, leftOut: { kind: string; name?: string }[] = []): Json {
    const out = (p: Json) => leftOut.some((l) => l.kind === p.kind && (l.kind === 'app' || l.name === p.name));
    const parts = PARTS(!!into).map((p): Json => ({ ...p, included: !out(p) }));
    const app = parts.find((p) => p.kind === 'app')!.included;
    const agents = parts.filter((p) => p.kind === 'agent' && p.included).map((p) => String(p.as));
    return {
        object: 'space_template_plan',
        dry_run: true,
        source: { kind: 'url', url: TEMPLATE_ADDRESS, commit: 'a3c9e01' },
        template: { name: 'Social media team', description: 'Plans, writes, designs and posts for your brand.', word: 'Social' },
        target: { workspace_id: into?.id ?? null, name: into?.name ?? 'Social media team', new: !into },
        parts,
        short: [],
        connections: [
            { integration: 'canva', label: 'Canva', node_type: 'automation-canva', for: ['Designer'], connected: null },
            { integration: 'instagram', label: 'Instagram', node_type: 'automation-instagram', for: ['Scheduler', 'Monday plan'], connected: null },
            { integration: 'linkedin', label: 'LinkedIn', node_type: 'automation-linkedin', for: ['Scheduler'], connected: { ref: 'credential:cr_linkedin', name: 'Rowan’s LinkedIn', id: 'credential:cr_linkedin' } },
            { integration: 'twitter', label: 'X', node_type: 'automation-twitter', for: ['Scheduler'], connected: null },
        ],
        secrets: [{ name: 'unsplash', keys: ['UNSPLASH_ACCESS_KEY'], description: 'Stock photos', for: ['Designer'], held: null, given: false }],
        cap: { usd_per_month: 40, from: 'template', agents: [{ name: agents[0], usd_per_month: 15 }] },
        app: app ? { name: 'content-calendar', runtime: 'edge', framework: null, account_key: null, secrets: { generated: [], asked: [] }, refused: null, missing_secrets: [] } : null,
        estimate: {
            object: 'estimate',
            estimated: true,
            monthly_usd: app ? 0.67 : 0,
            items: app
                ? [
                      { kind: 'project', label: 'App on the edge', name: 'content-calendar', monthly_usd: 0.49 },
                      { kind: 'repo', label: 'Repository', name: 'content-calendar', monthly_usd: 0.18 },
                  ]
                : [],
            agents: { up_to_usd: 40, names: agents, how: 'What its agents spend is by what they do: each turn’s model and the tools it calls, priced as it runs. They stop at $40 a month together.' },
        },
        funds: { ok: true },
        refused: null,
        summary: `Adds Social media team to ${into ? into.name : 'a new space, Social media team'}.`,
    };
}

const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();
const agentMember = (id: string, name: string, i: number) => ({ object: 'channel_member', id: `mem_${id}_${i}`, type: 'agent', agent_id: id, name, noclick: id === 'agt_social_nc', busy: false });

/** What the add makes, put into the spaces' fixture: the new space, its channels, its agents and the welcome post. */
export function seedTemplateWelcome(work: FakeWork): void {
    if (work.workspaces.some((w) => w.id === SOCIAL_SPACE)) return;
    const agents = [
        { id: 'agt_social_writer', name: 'Writer', role: 'Plans and drafts posts in the brand’s voice' },
        { id: 'agt_social_designer', name: 'Designer', role: 'Makes the images' },
        { id: 'agt_social_scheduler', name: 'Scheduler', role: 'Posts at the best times' },
    ];
    for (const a of agents) work.agents.push({ object: 'agent', id: a.id, name: a.name, role: a.role, harness: 'sdk', status: 'active', model: 'openrouter/openai/gpt-luna', instructions: `${a.role}.`, noclick: false });
    work.workspaces.unshift({
        object: 'workspace',
        id: SOCIAL_SPACE,
        name: 'Social media team',
        logo_url: null,
        status: 'active',
        user_id: null,
        channel_count: 4,
        people_limit: 50,
        members: agents.map((a, i) => ({ id: `wsm_social_${i}`, type: 'agent', agent_id: a.id, name: a.name, role: null })),
        created_at: at(30),
    });
    const channel = (id: string, name: string, topic: string, members: Json[]) => ({ object: 'channel', id, name, topic, mode: 'all', status: 'open', halt_reason: null, unread_count: 0, user_id: null, workspace_id: SOCIAL_SPACE, kind: 'channel', members, created_at: at(30) });
    const noclick = { id: 'agt_social_nc', name: 'NoClick' };
    work.channels.push(
        channel(SOCIAL_NOCLICK, 'noclick', 'Ask NoClick to change this space', [agentMember(noclick.id, noclick.name, 0)]),
        channel('ch_social_ideas', 'ideas', 'Where Writer plans the week’s posts.', [agentMember(agents[0].id, 'Writer', 0)]),
        channel('ch_social_drafts', 'drafts', 'Drafts and their images.', [agentMember(agents[0].id, 'Writer', 0), agentMember(agents[1].id, 'Designer', 1)]),
        channel('ch_social_scheduled', 'scheduled', 'What goes out, and how it did.', [agentMember(agents[2].id, 'Scheduler', 0)])
    );
    const links = Object.entries(TEMPLATE_LINKS).map(([id, l]) => ({ id, kind: 'connect', label: l.label, credential_type: l.credentialType, reason: l.reason, url: `https://noclick.test/credential/provide/${id}`, expires_at: null, integration: l.integration }));
    const secret = { kind: 'secret', id: TEMPLATE_SECRET, name: 'unsplash', keys: ['UNSPLASH_ACCESS_KEY'], reason: 'For Designer' };
    const message = (id: string, channelId: string, author: Json, text: string, secondsAgo: number, event: Json | null = null) => ({
        object: 'channel_message', id, channel_id: channelId, author, text, mentions: [], created_at: at(secondsAgo), attachments: [], reactions: [], reply_count: 0, last_reply_at: null, reply_authors: [], pinned: null, thread_id: null, also_in_channel: false, following: false, unread_replies: 0, event,
    });
    work.messages.set(SOCIAL_NOCLICK, [
        message(
            'msg_welcome',
            SOCIAL_NOCLICK,
            { type: 'agent', id: noclick.id, name: noclick.name },
            'Rowan added Social media team: Writer, Designer and Scheduler in #ideas, #drafts and #scheduled, the brand-voice skill, the brand memory, the Monday plan automation and the app content-calendar (live at https://content-calendar.noclick.site). Its agents stop at $40 a month.',
            20,
            {
                type: 'asks',
                turn: TEMPLATE_OPERATION,
                asked_by: null,
                asks: [...links, secret],
                options: [{ label: 'Plan this week’s posts', reply: 'Plan this week’s posts from last week’s results.', channel: 'ideas', channel_id: 'ch_social_ideas' }],
            }
        ),
    ]);
    work.messages.set('ch_social_ideas', [message('msg_hello_writer', 'ch_social_ideas', { type: 'agent', id: agents[0].id, name: 'Writer' }, 'Hi, I’m Writer. Plans and drafts posts in the brand’s voice. Where should I start? Pick one, or tell me what you need.', 15, { type: 'question', options: [{ label: 'Plan this week’s posts', reply: 'Plan this week’s posts from last week’s results.' }] })]);
}

const operation = (status: string, result: Json | null = null): Json => ({
    object: 'operation',
    id: TEMPLATE_OPERATION,
    kind: 'workspace.template_add',
    status,
    progress: { step: null, stages: [], lines: status === 'succeeded' ? [] : ['Building and deploying its app'], line_count: 1, updated_at: at(1) },
    workspace_id: result ? SOCIAL_SPACE : null,
    channel_id: result ? SOCIAL_NOCLICK : null,
    result,
    error: null,
    created_at: at(5),
});

const ADDED: Json = {
    object: 'space_template_added',
    template: { name: 'Social media team' },
    workspace: { id: SOCIAL_SPACE, name: 'Social media team', new: true },
    channel: { id: SOCIAL_NOCLICK, name: 'noclick' },
    message_id: 'msg_welcome',
    agents: [{ id: 'agt_social_writer', name: 'Writer' }, { id: 'agt_social_designer', name: 'Designer' }, { id: 'agt_social_scheduler', name: 'Scheduler' }],
    channels: [{ id: 'ch_social_ideas', name: 'ideas' }, { id: 'ch_social_drafts', name: 'drafts' }, { id: 'ch_social_scheduled', name: 'scheduled' }],
    app: { project_id: 'prj_calendar', name: 'content-calendar', url: 'https://content-calendar.noclick.site', to_reveal: [] },
    waiting: [{ integration: 'canva', label: 'Canva' }, { integration: 'instagram', label: 'Instagram' }, { integration: 'twitter', label: 'X' }],
    secrets: [{ id: TEMPLATE_SECRET, name: 'unsplash', keys: ['UNSPLASH_ACCESS_KEY'], for: ['Designer'] }],
};

const TEMPLATE_ROUTE = /^\/v1\/workspaces\/(?:from_template|([^/]+)\/template\/add)$/;

/** The template's routes over the spaces' fixture: the dry run, the add (which settles once `settle` is called, or at
 *  once when `settleAt` is 0), its operation's reads, its secret's values typed in (its welcome row read filled
 *  from then on, as the API reads it), and the gallery. Null for any other call. */
export function templateRoutes(work: FakeWork, options: { settleAfterMs?: number } = {}) {
    let state: 'none' | 'running' | 'succeeded' = 'none';
    const settle = () => {
        seedTemplateWelcome(work);
        state = 'succeeded';
        work.live.deliver('platform:resource', { kind: 'operation', id: TEMPLATE_OPERATION, status: 'succeeded' });
    };
    const answer = (method: string, path: string, body: Json): Response | null => {
        const route = method === 'POST' ? TEMPLATE_ROUTE.exec(path) : null;
        if (route) {
            const space = route[1] ? work.workspaces.find((w) => w.id === route[1]) : null;
            const leftOut = Array.isArray(body.leave_out) ? (body.leave_out as { kind: string; name?: string }[]) : [];
            const plan = templatePlan(space ? { id: String(space.id), name: String(space.name) } : null, leftOut);
            if (body.dry_run) return Response.json(plan);
            state = 'running';
            if (options.settleAfterMs !== undefined) setTimeout(settle, options.settleAfterMs);
            return Response.json({ object: 'space_template_add', template: plan.template, workspace: plan.target, operation: operation('running') }, { status: 202 });
        }
        if (method === 'GET' && path.startsWith(`/v1/operations/${TEMPLATE_OPERATION}`) && state !== 'none') return Response.json(operation(state, state === 'succeeded' ? ADDED : null));
        if (method === 'PATCH' && path === `/v1/secrets/${TEMPLATE_SECRET}`) {
            for (const m of work.messages.get(SOCIAL_NOCLICK) ?? []) {
                const event = m.event as { asks?: Json[] } | null;
                for (const ask of event?.asks ?? []) if (ask.id === TEMPLATE_SECRET) ask.state = 'succeeded';
            }
            const keys = Object.keys((body.values as Json | undefined) ?? {});
            return Response.json({ object: 'secret', id: TEMPLATE_SECRET, name: 'unsplash', keys, user_id: null, used_by: [{ kind: 'agent', id: 'agt_social_designer', name: 'Designer', binding: null }], moved_from: null, created_at: at(30), updated_at: at(0) });
        }
        return galleryRoutes(method, path);
    };
    return { answer, settle };
}
