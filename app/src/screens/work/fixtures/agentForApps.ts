// An agent an agents page made (POST /v1/agents/for_apps), as /v1 reads it back, for the labs and their tests: the
// Roblox agent on Hermes with its channel #roblox in the personal space. `waiting`: nothing connected yet, its model on
// a model connection still waiting for a key, its channel opening with what it needs. `ready`: Roblox connected and
// its model moved onto an OpenRouter key, its hello with first tasks to tap after that.
import { ANTHROPIC_KEY } from '@/screens/chat/fixtures/coordinatorSwitchers';
import { HARNESSES } from '../conversation/fixtures/workAgent';

type Json = Record<string, unknown>;
export type AgentForAppsState = 'waiting' | 'ready';

export const ROBLOX_AGENT_ID = 'agt_roblox';
export const ROBLOX_CHANNEL_ID = 'ch_roblox';
const MODEL_WAITING = 'roblox-agent-model';
const CREATED = '2026-11-27T09:00:00Z';
const later = (seconds: number) => new Date(Date.parse(CREATED) + seconds * 1000).toISOString();
const DESCRIPTION = 'Manage Roblox experiences and data stores, publish server messages, and watch entry revisions';

/** What it waited on when it was made, as the note and its channel's first message keep it. */
export const FOR_APPS_NEEDS: Json[] = [
    { kind: 'app', integration: 'roblox', node_type: 'automation-roblox', label: 'Roblox', description: DESCRIPTION },
    { kind: 'model' },
];

const ROBLOX: Json = { object: 'integration', name: 'roblox', label: 'Roblox', kind: 'app', credential_types: ['roblox_api_key'], operation_count: 12, account_free_operation_count: 0, events: [] };

const HERMES: Json = {
    name: 'hermes', label: 'Hermes', version: null, default_model: 'openrouter/~openai/gpt-luna-latest', custom_models: false, model_connection: 'required',
    integrations: ['openrouter', 'openai'], streaming: 'final', shell: 'built_in', notes: [], efforts: [], default_effort: null, speeds: [],
    noclick_key: { runs: false, models: [], why: 'Hermes Agent isn’t wired to NoClick’s key yet' },
};

export function robloxAgent(state: AgentForAppsState): Json {
    return {
        object: 'agent', id: ROBLOX_AGENT_ID, origin: 'api', name: 'Roblox agent', workflow_id: 'wf-roblox-agent', harness: 'hermes',
        model: 'openrouter/~openai/gpt-luna-latest', model_connection: state === 'ready' ? 'credential:cred-router' : MODEL_WAITING, role: DESCRIPTION,
        instructions: 'You’re the owner’s Roblox agent on NoClick.', tools: ['everything'], can_request: [], user_id: null, parent_id: null, status: 'idle',
        created_at: CREATED, last_active_at: null, running_turns: 0, child_count: 0, trigger_kinds: [], grants: [], added_in_app: [],
    };
}

const MEMBER: Json = { object: 'channel_member', id: 'mem_roblox', type: 'agent', name: 'Roblox agent', agent_id: ROBLOX_AGENT_ID, busy: false, created_at: CREATED };

export const ROBLOX_CHANNEL: Json = {
    object: 'channel', id: ROBLOX_CHANNEL_ID, name: 'roblox', topic: 'Where you talk to your Roblox agent.', mode: 'all', status: 'open', halt_reason: null,
    unread_count: 1, user_id: null, workspace_id: null, kind: 'channel', members: [MEMBER], created_at: CREATED,
};

const message = (id: string, author: Json, text: string, seconds: number, event: Json | null = null): Json => ({
    object: 'channel_message', id, channel_id: ROBLOX_CHANNEL_ID, author, text, mentions: [], created_at: later(seconds), attachments: [], reactions: [],
    reply_count: 0, last_reply_at: null, reply_authors: [], pinned: null, thread_id: null, also_in_channel: false, following: false, unread_replies: 0, event,
});
const AGENT_AUTHOR = { type: 'agent', id: ROBLOX_AGENT_ID, name: 'Roblox agent' };

/** Its channel's timeline: who joined, its ask, and once everything is in its hello. */
export function forAppsMessages(state: AgentForAppsState): Json[] {
    const joined = message('rb0', { type: 'system', id: null, name: 'NoClick' }, 'Roblox agent joined.', 0, {
        type: 'membership', action: 'added', by: { type: 'account', id: null, name: '' }, members: [{ id: 'mem_roblox', type: 'agent', name: 'Roblox agent', agent_id: ROBLOX_AGENT_ID, user_id: null }],
    });
    const asks = message('rb1', AGENT_AUTHOR, 'Hi, I’m your Roblox agent. I need two things before I can start: your Roblox account, and a model to think with.', 1, { type: 'connect', needs: FOR_APPS_NEEDS.map(({ description: _, ...n }) => n) });
    const hello = message(
        'rb2',
        AGENT_AUTHOR,
        `All set, I can start. What I can do:\n- Roblox: ${DESCRIPTION}\n\nWhere should I start? Pick one, or tell me what you need.`,
        240,
        {
            type: 'question',
            options: [
                { label: 'Show my experience', reply: 'Show me my experience in Roblox.' },
                { label: 'Show my data stores', reply: 'Show me my data stores in Roblox.' },
            ],
        }
    );
    return state === 'ready' ? [joined, asks, hello] : [joined, asks];
}

/** The account's connections as GET /v1/connections lists them: its Claude key, and its model's waiting connection; once
 *  ready, its Roblox account and the OpenRouter key its model runs on instead. */
export function forAppsConnections(state: AgentForAppsState): Json[] {
    if (state === 'waiting') {
        return [ANTHROPIC_KEY, { object: 'connection', id: 'conn-wait', name: MODEL_WAITING, integration: 'openrouter', credential_type: 'agent_openrouter', connected: false, status: 'pending', origin: 'api', access: 'owner', account: null, created_at: CREATED }];
    }
    return [
        ANTHROPIC_KEY,
        { object: 'connection', id: 'credential:cred-roblox', name: 'Roblox', integration: 'roblox', credential_type: 'roblox_api_key', connected: true, status: 'connected', origin: 'app', access: 'owner', account: 'Pet Tycoon', user_id: null, created_at: later(120), connected_at: later(120) },
        { object: 'connection', id: 'credential:cred-router', name: 'OpenRouter', integration: 'openrouter', credential_type: 'agent_openrouter', connected: true, status: 'connected', origin: 'app', access: 'owner', account: 'Key ending 9c1d', user_id: null, created_at: later(200), connected_at: later(200) },
    ];
}

/** The chat's note of its arrival, as the conversation keeps it. */
export function forAppsNote(): Json {
    return {
        role: 'note',
        text: 'Your Roblox agent is made, in #roblox. Connect Roblox and a model for Hermes on its card, then tell it what to work on there.',
        created_at: later(2),
        data: { setup: { kind: 'agent_for_apps', agent_id: ROBLOX_AGENT_ID, channel_id: ROBLOX_CHANNEL_ID, needs: FOR_APPS_NEEDS, client: 'hermes' } },
    };
}

const list = (data: Json[]) => Response.json({ object: 'list', data, next_cursor: null });

/** What /v1 answers of the agent, its channel, the account's connections and the harnesses (Hermes among them), by
 *  path; undefined for anything else. */
export function forAppsRoutes(state: AgentForAppsState) {
    return (method: string, path: string, query?: URLSearchParams, body?: unknown): Response | undefined => {
        // A post in its channel, as yours.
        if (method === 'POST' && path === `/v1/channels/${ROBLOX_CHANNEL_ID}/messages`)
            return Response.json(message('rb9', { type: 'account', id: null, name: 'Maya Lee' }, String((body as Json | undefined)?.text ?? ''), 300));
        if (method !== 'GET') return undefined;
        if (path === `/v1/agents/${ROBLOX_AGENT_ID}`) return Response.json(robloxAgent(state));
        if (path === `/v1/agents/${ROBLOX_AGENT_ID}/triggers`) return list([]);
        if (path === `/v1/channels/${ROBLOX_CHANNEL_ID}`) return Response.json(ROBLOX_CHANNEL);
        if (path === `/v1/channels/${ROBLOX_CHANNEL_ID}/messages`) return list(forAppsMessages(state));
        if (path === `/v1/channels/${ROBLOX_CHANNEL_ID}/triggers`) return list([]);
        if (path === '/v1/connections') return list(forAppsConnections(state));
        if (path === '/v1/harnesses') return list([...HARNESSES, HERMES]);
        if (path === '/v1/harnesses/hermes/models') return list([{ id: 'openrouter/~openai/gpt-luna-latest', label: 'GPT Luna' }]);
        // The apps an agent can use as tools, Roblox among them (the model providers are the fixtures' own).
        if (path === '/v1/integrations' && query?.get('kind') === 'app') return list([ROBLOX]);
        return undefined;
    };
}
