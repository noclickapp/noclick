// A fake /v1 for Work's agent views (the list, a profile, the New agent draft, the machine page): one space of five
// agents caught at different moments (two working, two waiting on you, one idle), or forty, with their harnesses,
// models, the account's AI accounts, triggers, wake-ups, turns, channels, skills, memories and a conversation's
// sandbox. The real platform client runs over it (workFixtureClient), so the views are exercised through the SDK.
import { workFixtureClient } from '../../fixtures/client';
import type { NoClick } from 'noclick';
import { firstSentence } from '../reads';
import { machineRoutes, machineStock, type MachineStock } from '../../machine/fixtures/machineStock';
import { machineWorldRoutes, runningNoClick, sampleDisk, type DiskEntry, type VettingStatus } from '../../machine/fixtures/machineWorld';

type Json = Record<string, unknown>;

export const NOW = Date.parse('2026-11-10T10:00:00.000Z');
const MIN = 60_000;
export const SPACE_ID = 'sp-noclick';
export const id = (n: number) => `a0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

/** What the account holds: an Anthropic key, a ChatGPT plan, all of them, or none yet. */
export type Keys = 'anthropic' | 'chatgpt' | 'several' | 'none';

interface Seed {
    name: string;
    harness: string;
    model: string;
    role: string;
    connection: string | null;
    state: string;
    now?: { tool: string; kind: string; line: string; since: number };
    waiting?: number;
    last?: number;
    budget?: number | null;
    failed?: string;
    waking?: string;
    machine?: string | null;
    /** Its tools as stored: `["noclick"]` when left out. */
    tools?: (string | Json)[];
}

const FIVE: Seed[] = [
    { name: 'Wirefern', harness: 'claude_code', model: 'opus', role: 'Knows the Wirefern code and its customers', connection: 'claude', state: 'working', now: { tool: 'Bash', kind: 'command', line: 'bash: pytest tests/test_retries.py', since: 4 * MIN }, budget: 25 },
    // Made with no tools: everything on the account, with the owner to tell and ask (the platform's default).
    { name: 'Support', harness: 'sdk', model: 'openrouter/anthropic/claude-sonnet-5.5', role: 'Answers customers on noclick.com', connection: 'anthropic', state: 'needs_you', waiting: 1, last: 12 * MIN, budget: 20, tools: ['everything', { human: { owner: true }, tools: ['notify', 'ask'] }] },
    { name: 'Growth', harness: 'claude_code', model: 'sonnet', role: 'Writes the guides and the pricing page', connection: 'claude', state: 'working', now: { tool: 'Edit', kind: 'edit', line: 'edit app/pricing/page.tsx', since: 6 * MIN }, budget: 15 },
    { name: 'Infra', harness: 'codex', model: 'gpt-5.6', role: 'Watches the servers, the CDN and the bills', connection: 'chatgpt', state: 'needs_you', waiting: 2, last: 40 * MIN, budget: 10, machine: 'm-ops-box' },
    { name: 'Release', harness: 'opencode', model: 'openai/gpt-5.6', role: 'Cuts releases and writes the changelog.', connection: 'openai', state: 'idle', last: 3 * 24 * 60 * MIN },
];

const MORE: Seed[] = [
    ['Books', 'codex', 'Keeps the books in Xero', 'working', 'bash: python reconcile.py --month 10', 11],
    ['Scout', 'claude_code', 'Finds leads on LinkedIn and in YC’s list', 'working', 'fetch linkedin.com/in/…', 2],
    ['Docs', 'opencode', 'Keeps the API docs in step with the code', 'working', 'edit docs/webhooks.md', 23],
    ['Triage', 'sdk', 'Labels new GitHub issues and finds duplicates', 'working', 'github: add_labels #4412', 0.6],
    ['Payouts', 'codex', 'Sends creators their monthly payouts', 'failed', 'Stripe refused the transfer', 25],
    ['Standup', 'hermes', 'Posts the team’s standup at 9:30', 'waking', 'Waking for the 9:30 standup', 0],
    ['Uptime', 'sdk', 'Checks noclick.com and the API every 5 minutes', 'idle', '', 4],
    ['Onboarding', 'sdk', 'Welcomes new accounts on WhatsApp', 'idle', '', 20],
    ['Calendar', 'sdk', 'Books your meetings and moves clashes', 'idle', '', 35],
    ['QA', 'claude_code', 'Clicks through staging after each deploy', 'idle', '', 50],
    ['Inbox', 'sdk', 'Sorts hello@ and drafts replies', 'idle', '', 60],
    ['Recruiter', 'claude_code', 'Screens applicants for the founding engineer role', 'idle', '', 120],
    ['Billing', 'sdk', 'Answers invoice questions and resends receipts', 'idle', '', 130],
    ['Expenses', 'openclaw', 'Files receipts from email into Ramp', 'idle', '', 180],
    ['Social', 'hermes', 'Drafts posts for X and LinkedIn', 'idle', '', 240],
    ['Changelog', 'opencode', 'Writes the weekly changelog from merged PRs', 'idle', '', 300],
    ['Data', 'codex', 'Answers questions from the Postgres replica', 'idle', '', 360],
    ['Refunds', 'sdk', 'Handles refund requests under $50', 'idle', '', 420],
    ['Security', 'codex', 'Reviews dependency updates and advisories', 'idle', '', 540],
    ['Ledger', 'codex', 'Reconciles Stripe payouts against the bank', 'idle', '', 1440],
    ['Churn', 'claude_code', 'Writes to accounts that went quiet', 'idle', '', 1500],
    ['SEO', 'claude_code', 'Tracks rankings and suggests guides to write', 'idle', '', 1600],
    ['Design QA', 'opencode', 'Checks screenshots against the design system', 'idle', '', 1700],
    ['Feedback', 'claude_code', 'Groups what customers ask for each week', 'idle', '', 1800],
    ['Translate', 'hermes', 'Translates the docs into Spanish and Hindi', 'idle', '', 2880],
    ['Status', 'sdk', 'Writes status-page updates during incidents', 'idle', '', 2900],
    ['Research', 'hermes', 'Reads papers and sums them up on Fridays', 'idle', '', 4320],
    ['Forecast', 'codex', 'Projects runway from the bank and Stripe', 'idle', '', 4400],
    ['Legal', 'claude_code', 'Reads contracts and flags odd clauses', 'idle', '', 5760],
    ['Partners', 'openclaw', 'Keeps the partner list and sends intros', 'idle', '', 7200],
    ['Hiring Ops', 'openclaw', 'Schedules interviews and sends offers', 'idle', '', 10080],
    ['Payroll', 'openclaw', 'Runs payroll on Gusto on the 25th', 'idle', '', 20160],
    ['Migrations', 'codex', 'Writes and checks database migrations', 'idle', '', 20200],
    ['Tax', 'codex', 'Collects what the accountant needs each quarter', 'idle', '', 60480],
    ['Archive', 'opencode', 'Moves old files to cold storage', 'idle', '', 43200 * 1.1],
].map(([name, harness, role, state, line, minutes]) => {
    const m = Number(minutes) * MIN;
    const model = { codex: 'gpt-5.6', claude_code: 'sonnet', opencode: 'openai/gpt-5.6', sdk: 'openrouter/openai/gpt-luna', hermes: 'openrouter/nousresearch/hermes-5', openclaw: 'anthropic/claude-sonnet-5.5' }[harness as string]!;
    return {
        name: name as string,
        harness: harness as string,
        model,
        role: role as string,
        connection: null,
        state: state as string,
        ...(state === 'working' ? { now: { tool: 'Bash', kind: String(line).startsWith('edit') ? 'edit' : 'command', line: line as string, since: m } } : {}),
        ...(state === 'failed' ? { failed: line as string, last: m } : {}),
        ...(state === 'waking' ? { waking: line as string } : {}),
        ...(state === 'idle' ? { last: m } : {}),
    } as Seed;
});

const HARNESSES: Json[] = [
    { name: 'sdk', label: 'NoClick', version: null, default_model: 'openrouter/openai/gpt-luna', custom_models: true, model_connection: 'optional', integrations: ['anthropic', 'openai', 'openrouter'], streaming: 'tokens', shell: 'code_capability', notes: [], efforts: ['low', 'medium', 'high'], default_effort: 'medium', speeds: [], noclick_key: { runs: true }, permission_modes: [], not_supported: {} },
    { name: 'claude_code', label: 'Claude Code', version: '2.1.295', default_model: 'sonnet', custom_models: false, model_connection: 'required', integrations: ['anthropic'], streaming: 'tokens', shell: 'built_in', notes: [], efforts: ['low', 'medium', 'high', 'max'], default_effort: 'high', speeds: ['standard', 'fast'], noclick_key: { runs: false, why: 'Claude Code runs on an Anthropic key or a Claude plan' }, permission_modes: ['approval-required', 'auto-accept-edits', 'auto', 'full-access'], not_supported: {} },
    { name: 'codex', label: 'Codex', version: '0.162.0', default_model: 'gpt-5.6', custom_models: false, model_connection: 'required', integrations: ['openai'], streaming: 'tokens', shell: 'built_in', notes: [], efforts: ['minimal', 'low', 'medium', 'high', 'xhigh'], default_effort: 'medium', speeds: ['standard', 'fast'], noclick_key: { runs: true, models: ['gpt-5.6'] }, permission_modes: ['approval-required', 'auto-accept-edits', 'auto', 'full-access'], not_supported: { questions: 'Codex can’t ask a person questions.' } },
    { name: 'opencode', label: 'OpenCode', version: '1.18.35', default_model: 'anthropic/claude-sonnet-5.5', custom_models: true, model_connection: 'required', integrations: ['anthropic', 'openai', 'openrouter', 'opencode'], streaming: 'tokens', shell: 'built_in', notes: [], efforts: ['default', 'high', 'max'], default_effort: 'default', speeds: [], noclick_key: { runs: true, models: ['openrouter/moonshotai/kimi-k3'] }, permission_modes: ['approval-required', 'auto-accept-edits', 'full-access'], not_supported: {} },
    { name: 'hermes', label: 'Hermes Agent', version: '2026.9.24', default_model: 'openrouter/nousresearch/hermes-5', custom_models: true, model_connection: 'required', integrations: ['anthropic', 'openai', 'openrouter'], streaming: 'final', shell: 'built_in', notes: [], efforts: ['none', 'low', 'medium', 'high'], default_effort: 'medium', speeds: [], noclick_key: { runs: false, why: 'Hermes doesn’t run on NoClick’s key yet' }, permission_modes: ['approval-required', 'auto', 'full-access'], not_supported: { 'approval-required': 'Hermes Agent asks only about commands its own checks flag as dangerous, so it runs approval-required as auto.', questions: 'Hermes Agent can’t ask a person questions.' } },
    { name: 'openclaw', label: 'OpenClaw', version: '2026.9.1', default_model: 'anthropic/claude-sonnet-5.5', custom_models: true, model_connection: 'required', integrations: ['anthropic', 'openai', 'openrouter'], streaming: 'tokens', shell: 'built_in', notes: [], efforts: ['off', 'minimal', 'low', 'medium', 'high'], default_effort: 'low', speeds: [], noclick_key: { runs: false, why: 'OpenClaw doesn’t run on NoClick’s key yet' }, permission_modes: ['full-access'], not_supported: { modes: 'OpenClaw runs every mode as full access.' } },
];

// Labelled as the harnesses' own model lists label them. One model reached several ways names its maker's model
// (`canonical`), as the API does; every other row is its own.
const SONNET = 'anthropic/claude-sonnet-5-5';
const MODELS: Record<string, Json[]> = {
    sdk: [
        { id: 'openrouter/openai/gpt-luna', label: '[openrouter] OpenAI: GPT Luna Latest' },
        { id: 'openrouter/anthropic/claude-sonnet-5.5', label: '[openrouter] Anthropic: Claude Sonnet 5.5' },
        { id: 'openrouter/openai/gpt-5.6', label: '[openrouter] OpenAI: GPT-5.6' },
    ],
    claude_code: [
        { id: 'sonnet', label: 'Sonnet 5.5' },
        { id: 'opus', label: 'Opus 5.5' },
        { id: 'haiku', label: 'Haiku 5.5' },
    ],
    codex: [
        { id: 'gpt-5.6', label: 'GPT-5.6' },
        { id: 'gpt-5.6-mini', label: 'GPT-5.6 mini' },
    ],
    opencode: [
        { id: 'anthropic/claude-sonnet-5.5', label: '[anthropic] Claude Sonnet 5.5 - 200K context', canonical: SONNET },
        { id: 'openai/gpt-5.6', label: '[openai] GPT-5.6 - 400K context · ChatGPT Plus' },
        { id: 'openrouter/anthropic/claude-sonnet-5.5', label: '[openrouter] Anthropic: Claude Sonnet 5.5 - 200K context', canonical: SONNET },
        { id: 'openrouter/moonshotai/kimi-k3', label: '[openrouter] MoonshotAI: Kimi K3 - 256K context' },
        { id: 'openrouter/z-ai/glm-5', label: '[openrouter] Z.ai: GLM-5 - Free - 200K context' },
        { id: 'opencode/claude-sonnet-5-5', label: '[OpenCode Zen] Claude Sonnet 5.5 - 200K context', canonical: SONNET },
        { id: 'opencode/big-pickle', label: '[OpenCode Zen] Big Pickle - Free - 200K context' },
    ],
    hermes: [
        { id: 'openrouter/nousresearch/hermes-5', label: '[OpenRouter] Hermes 5 - 128K ctx' },
        { id: 'anthropic/claude-sonnet-5.5', label: '[Anthropic] Claude Sonnet 5.5 - 200K ctx' },
    ],
    openclaw: [
        { id: 'anthropic/claude-sonnet-5.5', label: 'Claude Sonnet 5.5' },
        { id: 'openai/gpt-5.6', label: 'GPT-5.6' },
    ],
};

/** Each agent's sessions, the one it's in first (`main` alone where it isn't named). */
const CONVERSATIONS: Record<string, string[]> = { [id(1)]: ['main', 'retries-follow-up'] };

const MODEL_CONNECTIONS: Record<string, Json> = {
    anthropic: { name: 'anthropic', integration: 'anthropic', credential_type: 'agent_anthropic', status: 'connected', account: 'Key ending 4f2a' },
    'anthropic-personal': { name: 'personal', integration: 'anthropic', credential_type: 'agent_anthropic', status: 'connected', account: 'Key ending 91c7' },
    claude: { name: 'claude', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', status: 'connected', account: 'rowan@example.com' },
    chatgpt: { name: 'chatgpt', integration: 'openai', credential_type: 'agent_codex_oauth', status: 'connected', account: 'rowan@example.com' },
    openai: { name: 'openai', integration: 'openai', credential_type: 'agent_openai', status: 'connected', account: 'Key ending 7d10' },
    openrouter: { name: 'openrouter', integration: 'openrouter', credential_type: 'agent_openrouter', status: 'connected', account: 'Key ending 0b3e' },
};
/** The account's secrets by what they hold (ids, as the platform's, are UUIDs). */
export const SEC = { stripe: '5ec00000-0000-4000-8000-000000000001', gh: '5ec00000-0000-4000-8000-000000000002', npm: '5ec00000-0000-4000-8000-000000000003', linear: '5ec00000-0000-4000-8000-000000000004' };

/** The line a move adds to setup to write a carried file secret. */
export const NPMRC_SETUP = 'mkdir -p "$(dirname "$HOME/.npmrc")" && printf %s "$NC_FILE_NPMRC" | base64 -d > "$HOME/.npmrc" && chmod 600 "$HOME/.npmrc"';
const HELD: Record<Keys, string[]> = { anthropic: ['anthropic'], chatgpt: ['chatgpt'], several: Object.keys(MODEL_CONNECTIONS), none: [] };

const INTEGRATIONS: Json[] = [
    { name: 'anthropic', label: 'Claude', kind: 'model', subscription: true, connect_with: ['key'], credential_types: ['agent_anthropic', 'agent_claude_code_oauth'], operation_count: 0, account_free_operation_count: 0, events: [] },
    { name: 'openai', label: 'ChatGPT', kind: 'model', subscription: true, connect_with: ['key'], credential_types: ['agent_openai', 'agent_codex_oauth'], operation_count: 0, account_free_operation_count: 0, events: [] },
    { name: 'openrouter', label: 'OpenRouter', kind: 'model', subscription: false, connect_with: ['key'], credential_types: ['agent_openrouter'], operation_count: 0, account_free_operation_count: 0, events: [] },
    { name: 'opencode', label: 'OpenCode Zen', kind: 'model', subscription: false, connect_with: ['key'], credential_types: ['agent_opencode'], operation_count: 0, account_free_operation_count: 0, events: [] },
    // Labelled as the API labels apps, its id title-cased; credential types as the catalog's nodes accept them.
    { name: 'github', label: 'Github', kind: 'app', subscription: false, connect_with: ['oauth'], credential_types: ['github_oauth', 'github_pat'], operation_count: 40, account_free_operation_count: 0, events: ['pull_request_opened', 'issue_opened', 'push'] },
    { name: 'hubspot', label: 'Hubspot', kind: 'app', subscription: false, connect_with: ['oauth'], credential_types: ['hubspot_oauth', 'hubspot_pat'], operation_count: 60, account_free_operation_count: 0, events: ['contact_created'] },
    { name: 'whatsapp', label: 'Whatsapp', kind: 'app', subscription: false, connect_with: ['qr'], credential_types: ['whatsapp_qr', 'whatsapp_access_token'], operation_count: 10, account_free_operation_count: 0, events: ['message_received'] },
    { name: 'posthog', label: 'Posthog', kind: 'app', subscription: false, connect_with: ['key'], credential_types: ['posthog_personal_api_key', 'posthog_project_api_key', 'posthog_oauth'], operation_count: 15, account_free_operation_count: 0, events: ['action_performed'] },
    { name: 'stripe', label: 'Stripe', kind: 'app', subscription: false, connect_with: ['key'], credential_types: ['stripe_oauth', 'stripe_api_key'], operation_count: 30, account_free_operation_count: 0, events: ['payment_failed', 'charge_disputed', 'invoice_paid'] },
    { name: 'slack', label: 'Slack', kind: 'app', subscription: false, connect_with: ['oauth'], credential_types: ['slack_oauth', 'slack_bot_token'], operation_count: 50, account_free_operation_count: 0, events: ['channel_message', 'app_mention'] },
    { name: 'gmail', label: 'Gmail', kind: 'app', subscription: false, connect_with: ['oauth'], credential_types: ['google_gmail_oauth'], operation_count: 20, account_free_operation_count: 0, events: ['new_email'] },
];
const EVENTS: Record<string, Json[]> = {
    github: [
        { name: 'pull_request_opened', description: 'A pull request is opened on a repository', filters: { repository: 'Required. owner/name' } },
        { name: 'issue_opened', description: 'An issue is opened', filters: { repository: 'Required. owner/name', label: 'Only issues with this label' } },
        { name: 'push', description: 'Commits are pushed', filters: { repository: 'Required. owner/name', branch: 'Only this branch' } },
    ],
    stripe: [
        { name: 'payment_failed', description: 'A payment fails', filters: {} },
        { name: 'charge_disputed', description: 'A customer disputes a charge', filters: {} },
        { name: 'invoice_paid', description: 'An invoice is paid', filters: {} },
    ],
    slack: [
        { name: 'channel_message', description: 'A message in a channel', filters: { channel: 'Required. A channel id' } },
        { name: 'app_mention', description: 'Someone @-mentions the app', filters: {} },
    ],
    gmail: [{ name: 'new_email', description: 'A new email arrives', filters: { label: 'Only mail with this label' } }],
};

export interface FakeWork {
    client: NoClick;
    /** The fake's own fetch, which `client` runs over: another client (a lab putting fixtures together) can too. */
    fetch: typeof window.fetch;
    requests: { method: string; path: string; query: URLSearchParams; body: unknown }[];
    agents: Json[];
    states: Json[];
    triggers: Map<string, Json[]>;
    operations: Json[];
    /** Changes an agent's state row, as a turn moving would. */
    setState: (agentId: string, change: Json) => void;
    /** What the views made beside the agents: connections, inboxes, space memberships. */
    created: { connections: Json[]; inboxes: Json[]; members: Json[] };
    /** The account's machines, as GET /v1/machines lists them. */
    machines: Json[];
    /** Moves the laptop move on, as the agent running the guide would. */
    moveTo: (change: Json) => void;
    /** Each agent's conversations' tool servers, as GET …/tool_servers answers (`<agentId>/<conversation>`). */
    toolServers: Map<string, Json>;
    /** The account's secrets, as GET /v1/secrets lists them. */
    secrets: Json[];
    /** Each agent's one /workspace, as GET /v1/agents/{id}/workspace lists it (Wirefern' holds a WhatsApp inbox). */
    workspaces: Map<string, Json[]>;
    /** Whether agents run on machines on this deployment (GET /v1/machines' `agents_enabled`); a test may flip it. */
    machinesEnabled: { value: boolean };
    /** What new machines can be bought and where; a test may run a host out of a size (`stock.out`). */
    stock: MachineStock;
    /** Where the account's company check for machines stands (`GET /v1/machines/vetting`); a test may change it. */
    vetting: { value: Json };
    /** Each machine's disk, by absolute path, as its Files lists it. */
    disks: Map<string, Map<string, DiskEntry>>;
    /** Fails the next request matching `method path`, once. */
    failNext: (method: string, path: string, status?: number, message?: string) => void;
    /** Someone signs in at a connection's link: it's connected to `account`, its link spent. */
    signIn: (name: string, account: string | null) => void;
    /** A key saved or a plan signed in to in the app, as the API lists it: `credential:<id>`, named as it was saved,
     *  `account` who it signed in as. */
    addAppAccount: (credentialId: string, name: string, integration: string, credentialType: string, account?: string) => void;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const list = (data: unknown[]) => json({ object: 'list', data, next_cursor: null });
const notFound = (message: string) => json({ error: { type: 'not_found', message } }, 404);

/** A rename as PATCH /v1/agents/{id} judges it: a name another agent has or went by is refused, saying whose; a NoClick
 *  keeps its name; one renamed keeps its old name in `former_names` (renamed back, it has it again). Null when it may. */
export function renameRefused(agents: Json[], agent: Json, body: Json): Response | null {
    const name = body.name;
    if (typeof name !== 'string' || name === agent.name) return null;
    if (agent.noclick) return json({ error: { type: 'conflict', message: 'NoClick keeps its own name, so it can’t be renamed.', field: 'name' } }, 409);
    const taken = agents.find((a) => a !== agent && a.name === name);
    if (taken) return json({ error: { type: 'conflict', message: `An agent named '${name}' already exists.`, next_step: 'Use the existing agent, or pick another name.', existing_id: taken.id } }, 409);
    const went = agents.find((a) => a !== agent && ((a.former_names as string[] | undefined) ?? []).includes(name));
    if (went)
        return json({ error: { type: 'conflict', message: `'${name}' was the name of the agent now called '${went.name}', and stays reserved for it so anything still using the old name reaches it.`, field: 'name', existing_id: went.id } }, 409);
    agent.former_names = [agent.name, ...((agent.former_names as string[] | undefined) ?? []).filter((n) => n !== name)];
    return null;
}

/** The account's coordinator, as the platform makes it: its role is its instructions' first sentence, full stop and all;
 *  flagged a NoClick (`noclick`), as the platform flags every NoClick it lists. */
export const COORDINATOR_ROLE = 'You are NoClick, the account’s assistant: the one agent that sees this whole account and gets things done in it.';

/** The space's own NoClick, as the platform names (`noclick-<the space's id>`) and flags it (`noclick`). */
export const SPACE_NOCLICK_ID = id(90);

/** An app's coding agent, one of NoClick's helpers. */
export const HELPER_ID = id(91);

/** A trigger as the API reads it since triggers say when they fire (`state`, `fix`, `actions`, …), from its row. */
function triggerView(row: Json, agentPaused: boolean): Json {
    const kind = String(row.kind);
    const paused = row.paused === true;
    const stoppedItself = row.stopped === true;
    const state = agentPaused || paused ? 'paused' : row.error ? 'stopped' : 'live';
    const actions = ['email', 'app', 'routine'].includes(kind)
        ? ['test']
        : kind === 'channel'
          ? ['test', 'update']
          : ['call', 'approval'].includes(kind)
            ? []
            : [...(paused || stoppedItself ? ['resume'] : []), ...(paused ? [] : ['pause']), 'test', 'update', 'remove'];
    const fix = state === 'live' ? null : agentPaused ? { action: 'resume_agent' } : paused || stoppedItself ? { action: 'resume' } : (row.fix ?? null);
    return {
        object: 'agent_trigger',
        ...row,
        status: state === 'paused' ? 'paused' : state === 'stopped' ? 'error' : 'active',
        next_run: state === 'live' ? (row.next_run ?? null) : null,
        paused,
        state,
        reason: agentPaused ? 'The agent is paused, so nothing wakes it until it’s resumed.' : paused ? 'Paused: it doesn’t wake the agent until it’s resumed.' : (row.error ?? null),
        fix,
        next_run_at: row.next_run_at ?? row.next_run ?? null,
        set_by: row.set_by ?? { kind: 'person', agent_id: null },
        read_only: ['app', 'email', 'call', 'approval', 'routine'].includes(kind),
        running: row.running === true,
        actions,
    };
}

// What an agent may do with each app (GET /v1/agents/{id}/tool_access), as the platform reads it for the account's two
// apps, NoClick and the web: WhatsApp used this week, GitHub with more actions than fit, so it searches and groups.
const GITHUB_ACTIONS: [string, string, string][] = [
    ['Issues', 'read', 'list_issues'], ['Issues', 'read', 'get_issue'], ['Issues', 'change', 'create_issue'], ['Issues', 'change', 'update_issue'], ['Issues', 'change', 'add_labels'],
    ['Issues', 'delete', 'delete_comment'], ['Pull requests', 'read', 'list_pull_requests'], ['Pull requests', 'change', 'create_pull_request'], ['Pull requests', 'change', 'merge_pull_request'],
    ['Pull requests', 'read', 'get_pull_request_diff'], ['Pull requests', 'send', 'request_reviewers'], ['Repositories', 'read', 'list_repositories'], ['Repositories', 'change', 'create_repository'],
    ['Repositories', 'delete', 'delete_repository'], ['Repositories', 'change', 'update_repository'], ['Repositories', 'read', 'get_file_contents'], ['Actions', 'read', 'list_workflow_runs'],
    ['Actions', 'change', 'rerun_workflow'], ['Actions', 'change', 'cancel_workflow_run'], ['Actions', 'read', 'download_workflow_logs'],
];
const WHATSAPP_ACTIONS: [string, string, string, number][] = [
    ['Message', 'send', 'send_text_message', 30], ['Chats', 'read', 'get_chat_messages', 11], ['Message', 'send', 'send_reaction_emoji', 0], ['Message', 'delete', 'delete_message', 0],
];
const words = (op: string) => op.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

/** The rules a list of tools amounts to: what it names on, the rest off (``tool_rules.from_tools``). */
function rulesOfList(tools: unknown[]): Record<string, string> {
    const rules: Record<string, string> = { '*': 'off' };
    for (const t of tools) if (typeof t === 'string' && t !== 'code') rules[t] = 'allow';
    return rules;
}

export function toolAccessOf(agent: Json): Json {
    const tools = (agent.tools as unknown[]) ?? [];
    const listed = !tools.includes('everything');
    const rules = { ...(listed ? rulesOfList(tools) : {}), ...((agent.tool_rules as Record<string, string>) ?? {}) };
    const act = (app: string, [group, kind, name, calls = 0]: [string, string, string, number?], key = `${app}.${name}`) => ({ key, action: name, title: words(name), group, kind, verdict: 'allow', can_ask: true, calls });
    const app = (key: string | null, appName: string, kind: string, label: string, account: string, actions: Json[], extra: Json = {}) => ({
        key, app: appName, kind, integration: null, credential_type: null, label, account, status: null, on: true, calls: actions.reduce((n, a) => n + Number(a.calls), 0), actions, ...extra,
    });
    return {
        object: 'agent_tool_access', agent_id: agent.id, mode: rules['*'] === 'off' ? 'restricted' : 'everything', listed, rules, since: new Date(NOW - 7 * 24 * 60 * MIN).toISOString(),
        apps: [
            app('credential:c-wa', 'credential:c-wa', 'connection', 'WhatsApp', '+1 202 555 0101', WHATSAPP_ACTIONS.map((a) => act('credential:c-wa', a)), { integration: 'whatsapp', credential_type: 'whatsapp_qr', status: 'connected' }),
            app('credential:c-gh', 'credential:c-gh', 'connection', 'GitHub', 'acme', GITHUB_ACTIONS.map((a) => act('credential:c-gh', a)), { integration: 'github', credential_type: 'github_oauth', status: 'connected' }),
            app('noclick', 'noclick', 'noclick', 'NoClick', 'Build, deploy, spend', [['', 'read', 'read', 3], ['', 'change', 'build'], ['', 'change', 'deploy'], ['', 'money', 'spend'], ['', 'delete', 'delete']].map((a) => ({ ...act('noclick', a as [string, string, string, number]), group: null, can_ask: a[2] !== 'read' }))),
            app(null, 'web', 'web', 'Web', 'Search and read pages', [act('web', ['', 'read', 'search', 18], 'search'), act('web', ['', 'read', 'fetch'], 'fetch')].map((a) => ({ ...a, group: null }))),
        ],
    };
}

export function fakeWork(options: { count?: 5 | 40; keys?: Keys; sandbox?: 'running' | 'stopped'; now?: number; coordinator?: boolean; spaceNoClick?: boolean; helper?: boolean; machinesEnabled?: boolean; moved?: boolean | 'sign-ins'; pairingForms?: boolean; triggersApi?: 'v2'; machineHosts?: 'two' | 'one'; vetting?: VettingStatus; answerAfter?: (method: string, path: string, query: URLSearchParams) => Promise<void> | undefined } = {}): FakeWork {
    // The clock its times are read against: the tests' fixed one, or the preview's own.
    const clock = options.now ?? NOW;
    /** A fresh code's pairing, as the API answers it once (a read later carries neither the code nor its command). */
    // The command for Linux (Windows runs it in WSL), and a Mac's without sudo, each again with --yes to run unattended;
    // an API from before the forms gives none.
    const pairingFor = (code: string) => {
        const linux = `curl -fsSL https://api.noclick.com/v1/machines/machine.sh | sudo sh -s -- --code ${code}`;
        const mac = linux.replace(' | sudo sh ', ' | sh ');
        const commands = options.pairingForms === false ? null : { linux, mac, linux_unattended: `${linux} --yes`, mac_unattended: `${mac} --yes` };
        return { code, command: linux, commands, expires_at: new Date(Date.now() + 30 * MIN).toISOString(), installing_on: null, refused: null };
    };
    const ago = (ms: number) => new Date(clock - ms).toISOString();
    const seeds = options.count === 40 ? [...FIVE, ...MORE] : FIVE;
    const held = HELD[options.keys ?? 'several'];
    // Agents deleted to the trash, by their trash id, with where they stood in the lists.
    const trash = new Map<string, { agent: Json; state: Json; at: number }>();
    const agents: Json[] = seeds.map((s, i) => ({
        object: 'agent', id: id(i + 1), origin: 'api', name: s.name, role: s.role, workflow_id: `wf-${i + 1}`, model: s.model, harness: s.harness, model_connection: s.connection,
        instructions: `${s.role.replace(/\.$/, '')}.`, tools: s.tools ?? ['noclick'], can_request: [], user_id: null, parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: s.budget ?? null,
        region: null, timezone: 'Europe/London', secret_ids: [], volumes: {}, memory_id: `mem-${i + 1}`, memories: [], repos: [], shell: true, network: true, machine_id: s.machine ?? null,
        browser_profile_id: null, card_id: null, turn_limits: null, used_by: [], helper: false, noclick: false, former_names: [], created_at: ago(30 * 24 * 60 * MIN), status: s.state === 'working' ? 'working' : 'idle',
        last_active_at: s.last ? ago(s.last) : ago(0), running_turns: s.state === 'working' ? 1 : 0, child_count: 0, job_id: null, paused: false, trigger_kinds: [], effort: null, speed: null, skills: [],
        docker: false, sandbox_size: null, app_testing: 'by_itself', app_testing_usd_per_hour: s.harness === 'sdk' || s.machine ? null : 0.44,
        ...(i === 0 ? { skills: [{ id: 'sk-1', pin: null }, { id: 'sk-2', pin: null }], memories: [{ id: 'mem-team', writes: true }] } : {}),
    }));
    const states: Json[] = seeds.map((s, i) => ({
        agent_id: id(i + 1), name: s.name, noclick: false, harness: s.harness, state: s.state, conversation: s.state === 'idle' ? null : 'main',
        now: s.now ? { ...s.now, since: ago(s.now.since) } : null,
        waiting: { asks: s.waiting ? 1 : 0, held_calls: s.waiting ? s.waiting - 1 : 0, requests: 0, total: s.waiting ?? 0 },
        turn_started_at: s.now ? ago(s.now.since) : null, last_active_at: s.last !== undefined ? ago(s.last) : ago(0),
        failed: s.failed ? { message: s.failed, at: ago(s.last ?? 0) } : null, waking: s.waking ? { at: ago(-MIN / 2), why: s.waking } : null,
    }));
    if (options.coordinator) {
        const n = agents.length + 1;
        agents.push({
            ...agents[1], id: id(n), name: 'coordinator', role: COORDINATOR_ROLE, instructions: `${COORDINATOR_ROLE} You answer the owner on every channel.`, harness: 'sdk',
            model: 'openrouter/openai/gpt-luna', model_connection: null, user_id: null, memory_id: `mem-${n}`, budget_usd_per_month: null, status: 'idle', running_turns: 0, last_active_at: ago(3 * 60 * MIN),
            noclick: true,
        });
        states.push({ agent_id: id(n), name: 'coordinator', noclick: true, harness: 'sdk', state: 'idle', conversation: null, now: null, waiting: { asks: 0, held_calls: 0, requests: 0, total: 0 }, turn_started_at: null, last_active_at: ago(3 * 60 * MIN), failed: null, waking: null });
    }
    if (options.spaceNoClick) {
        const name = `noclick-${'5'.repeat(32)}`;
        agents.push({ ...agents[1], id: SPACE_NOCLICK_ID, name, role: null, instructions: 'You keep this space.', harness: 'sdk', model_connection: null, budget_usd_per_month: null, status: 'idle', running_turns: 0, noclick: true });
        states.push({ agent_id: SPACE_NOCLICK_ID, name, noclick: true, harness: 'sdk', state: 'idle', conversation: null, now: null, waiting: { asks: 0, held_calls: 0, requests: 0, total: 0 }, turn_started_at: null, last_active_at: ago(60 * MIN), failed: null, waking: null });
    }
    // An app's coding agent, which NoClick made when the account's assistant handed the app a change (`helper`): at work
    // on it now, a question of its harness's waiting.
    if (options.helper) {
        agents.push({ ...agents[3], id: HELPER_ID, name: 'shop-coder', role: 'Makes the code changes NoClick’s assistant hands it for shop', instructions: 'You change an app’s code for NoClick’s assistant.', harness: 'codex', model_connection: 'noclick', budget_usd_per_month: 10, machine_id: null, memory_id: 'mem-helper', helper: true, status: 'working', running_turns: 1 });
        states.push({ agent_id: HELPER_ID, name: 'shop-coder', harness: 'codex', state: 'needs_you', conversation: 'code', now: null, waiting: { asks: 0, held_calls: 0, requests: 1, total: 1 }, turn_started_at: ago(2 * MIN), last_active_at: ago(0), failed: null, waking: null });
    }
    // Wirefern, moved from a laptop: its Claude plan, three secrets (its environment, a file, a tool server's header),
    // its own git remote and the setup that installs its CLI and writes the file. One secret of the account's it had already.
    const MOVED = { move_id: 'mv-laptop', host: 'rowan-mbp', folder: '~/code/wirefern', at: ago(2 * 24 * 60 * MIN) };
    const secrets: Json[] = [{ object: 'secret', id: SEC.stripe, name: 'stripe-test', keys: ['STRIPE_KEY'], user_id: null, moved_from: null }];
    const deletedConnections = new Set<string>();
    const signedIn: { notion?: string } = {};
    // A move stamps the agent it made with where it came from (`moved_from`, kept after the move is pruned).
    if (options.moved) Object.assign(agents[0], { moved_from: { move_id: MOVED.move_id, host: MOVED.host, folder: MOVED.folder, at: MOVED.at } });
    // 'sign-ins': a move that carried only a tool server signed in to in a browser, so nothing else says it moved.
    if (options.moved === true) {
        secrets.push(
            { object: 'secret', id: SEC.gh, name: 'github-token', keys: ['GH_TOKEN'], user_id: null, moved_from: { ...MOVED, to: { env: 'GH_TOKEN' } } },
            { object: 'secret', id: SEC.npm, name: 'npmrc', keys: ['NC_FILE_NPMRC'], user_id: null, moved_from: { ...MOVED, to: { file: '~/.npmrc', mode: '600' } } },
            { object: 'secret', id: SEC.linear, name: 'linear-api-key', keys: ['VALUE'], user_id: null, moved_from: { ...MOVED, to: {} } }
        );
        Object.assign(agents[0], {
            secret_ids: [SEC.stripe, SEC.gh, SEC.npm, SEC.linear],
            setup: ['npm i -g @linear/cli', NPMRC_SETUP],
            repos: [{ url: 'https://github.com/acme/wirefern.git', branch: 'noclick/move', path: 'wirefern', push: ['noclick/*'], secret: SEC.gh, secret_key: 'GH_TOKEN', username: 'x-access-token' }],
        });
    }
    const triggers = new Map<string, Json[]>([
        [id(1), [
            { id: 't-1', kind: 'event', spec: { kind: 'event', connection: 'github', event: 'issue_opened', filters: { repository: 'acme/wirefern', label: 'bug' } }, status: 'active', url: null, next_run: null, last_fired_at: ago(3 * 60 * MIN), error: null, created_at: ago(20 * 24 * 60 * MIN) },
            { id: 't-2', kind: 'cron', spec: { kind: 'cron', cron: '0 9 * * 1-5', tz: 'Europe/London', message: 'Check last night’s failed deliveries.' }, status: 'active', url: null, next_run: ago(-23 * 60 * MIN), last_fired_at: ago(60 * MIN), error: null, created_at: ago(20 * 24 * 60 * MIN) },
        ]],
        [id(2), [
            { id: 't-3', kind: 'email', spec: { kind: 'email', address: 'support@wirefern.test' }, status: 'active', url: null, next_run: null, last_fired_at: ago(12 * MIN), error: null, created_at: ago(9 * 24 * 60 * MIN) },
            { id: 't-4', kind: 'event', spec: { kind: 'event', connection: 'stripe', event: 'charge_disputed', filters: {} }, status: 'active', url: null, next_run: null, last_fired_at: null, error: null, created_at: ago(9 * 24 * 60 * MIN) },
        ]],
        [id(4), [
            { id: 't-5', kind: 'webhook', spec: { kind: 'webhook', name: 'cdn-alerts' }, status: 'active', url: 'https://hooks.noclick.test/t-5', next_run: null, last_fired_at: ago(40 * MIN), error: null, created_at: ago(9 * 24 * 60 * MIN) },
            { id: 't-6', kind: 'cron', spec: { kind: 'cron', cron: '0 9 * * 1-5', tz: 'Europe/London' }, status: 'active', url: null, next_run: ago(-23 * 60 * MIN), last_fired_at: ago(60 * MIN), error: null, created_at: ago(9 * 24 * 60 * MIN) },
        ]],
    ]);
    if (options.triggersApi === 'v2')
        // What the API reads for it since triggers say when they fire: one stopped (its key revoked), one paused, the
        // channel it sits in, and a routine it set itself.
        triggers.set(id(1), [
            ...triggers.get(id(1))!,
            { id: 't-7', kind: 'event', spec: { kind: 'event', connection: 'stripe', event: 'charge_disputed', filters: {} }, url: null, next_run: null, last_fired_at: ago(2 * 24 * 60 * MIN), error: 'Stripe refused the key: it was revoked.', fix: { action: 'connect', connection: 'stripe' }, created_at: ago(9 * 24 * 60 * MIN) },
            { id: 't-8', kind: 'webhook', spec: { kind: 'webhook', name: 'deploys' }, url: 'https://hooks.noclick.test/t-8', paused: true, next_run: null, last_fired_at: ago(5 * 24 * 60 * MIN), error: null, created_at: ago(9 * 24 * 60 * MIN) },
            { id: 'ch-launch', kind: 'channel', channel_id: 'ch-launch', spec: { channel_id: 'ch-launch', name: 'launch', mode: 'all' }, url: null, next_run: null, last_fired_at: ago(30 * MIN), error: null, created_at: ago(30 * 24 * 60 * MIN) },
            { id: 'w-r1', kind: 'routine', spec: { cron: '0 8 * * 1', tz: 'Europe/London', note: 'Write the weekly summary.', conversation: 'main' }, url: null, next_run: null, next_run_at: ago(-5 * 24 * 60 * MIN), last_fired_at: ago(2 * 24 * 60 * MIN), error: null, set_by: { kind: 'agent', agent_id: id(1) }, created_at: ago(9 * 24 * 60 * MIN) },
        ]);
    const viewOf = (agentId: string, row: Json) => (options.triggersApi === 'v2' ? triggerView(row, agents.find((a) => a.id === agentId)?.paused === true) : row);
    const operations: Json[] = [
        { object: 'operation', id: 'op-1', kind: 'agent.message', status: 'running', step: 'working', agent_id: id(1), conversation: 'main', title: 'Fix webhook retries', result: null, error: null, created_at: ago(4 * MIN), updated_at: ago(MIN), started_at: ago(4 * MIN), finished_at: null },
        { object: 'operation', id: 'op-2', kind: 'agent.message', status: 'succeeded', step: null, agent_id: id(1), conversation: 'main', title: null, result: { text: 'Opened #4410 with the fix for the retry worker.', conversation: 'main', tool_calls: [], cost_usd: 0.42 }, error: null, created_at: ago(26 * 60 * MIN), updated_at: ago(26 * 60 * MIN - 9 * MIN), started_at: ago(26 * 60 * MIN), finished_at: ago(26 * 60 * MIN - 9 * MIN) },
        { object: 'operation', id: 'op-3', kind: 'agent.message', status: 'failed', step: null, agent_id: id(1), conversation: 'issue-4398', title: null, result: null, error: { type: 'upstream_error', message: 'GitHub didn’t answer.' }, created_at: ago(3 * 24 * 60 * MIN), updated_at: ago(3 * 24 * 60 * MIN), started_at: ago(3 * 24 * 60 * MIN), finished_at: ago(3 * 24 * 60 * MIN - MIN) },
    ];
    const wakeups: Json[] = [
        { object: 'wakeup', id: 'w-1', agent_id: id(1), user_id: null, conversation: 'main', note: 'Check whether the retries held overnight.', at: ago(-14 * 60 * MIN), when: null, every: null, fired: 0, source: 'wake_me', status: 'pending', created_at: ago(30 * MIN) },
    ];
    const channels: Json[] = [
        { object: 'channel', id: 'ch-launch', name: 'launch', topic: '', mode: 'all', workspace_id: SPACE_ID, members: [{ type: 'agent', agent_id: id(1) }, { type: 'agent', agent_id: id(2) }], unread_count: 0, status: 'open', created_at: ago(30 * 24 * 60 * MIN) },
        { object: 'channel', id: 'ch-incidents', name: 'incidents', topic: '', mode: 'mentions', workspace_id: SPACE_ID, members: [{ type: 'agent', agent_id: id(1) }, { type: 'agent', agent_id: id(4) }], unread_count: 0, status: 'open', created_at: ago(30 * 24 * 60 * MIN) },
    ];
    // Infra works on it now.
    const machines: Json[] = [
        {
            object: 'machine', id: 'm-ops-box', name: 'ops-box', kind: 'noclick', status: 'running', size: 'small', region: 'us-east', cpu: 2, memory_gb: 4, disk_gb: 80, monthly_usd: 31.2, docker: false, app_testing: 'never', created_at: ago(12 * 24 * 60 * MIN),
            ...runningNoClick(clock, { working_count: 1, agent_states: [{ agent_id: id(4), working: true }], ports: [{ object: 'machine_port', port: 3000, url: 'https://ops-box-3000.noclick.test', public: true }] }),
        },
    ];
    const vettingStatus = options.vetting ?? 'approved';
    const vetting = {
        value: (vettingStatus === 'not_submitted'
            ? { object: 'machine_vetting', status: 'not_submitted', policy_version: '2026-10-08' }
            : { object: 'machine_vetting', status: vettingStatus, company_name: 'Example Commerce', website: 'example.com', country: 'GB', use_case: 'Agents keep the shop’s tests green and answer support email.', policy_version: '2026-10-08', submitted_at: ago(60 * MIN), decided_at: null, reason: vettingStatus === 'rejected' ? 'We couldn’t find a company at example.com.' : null }) as Json,
    };
    const disks = new Map<string, Map<string, DiskEntry>>([['m-ops-box', sampleDisk(clock)]]);
    const fails: { method: string; path: string; status: number; message: string }[] = [];
    const toolServers = new Map<string, Json>([
        [
            `${id(1)}/main`,
            {
                object: 'tool_servers',
                data: [
                    { name: 'GitHub MCP', status: 'connected', tool_count: 41, error: null },
                    { name: 'Sentry', status: 'failed', tool_count: null, error: 'The server answered 401: its token has expired.' },
                ],
                source: 'live',
                checked_at: ago(MIN),
                reconnect: { available: true, scope: 'server', why: null },
            },
        ],
    ]);
    const machinesEnabled = { value: options.machinesEnabled ?? true };
    // A machine's choice for its agents' app testing, as the API takes it (docker alone chooses), and the docker it gives.
    const appTestingOf = (body: Json, otherwise: string) => {
        const chosen = typeof body.app_testing === 'string' ? body.app_testing : typeof body.docker === 'boolean' ? (body.docker ? 'by_itself' : 'never') : otherwise;
        return { app_testing: chosen, docker: chosen !== 'never' };
    };
    const stock = machineStock(options.machineHosts ?? 'two');
    const NOT_ON_MACHINES = "Agents on machines aren't enabled on this deployment yet.";
    const notOnMachines = () => json({ error: { type: 'not_available', message: NOT_ON_MACHINES, field: 'machine_id' } }, 409);
    const requests: FakeWork['requests'] = [];
    let made = 0;
    let move: Json | null = null;
    const created = { connections: [] as Json[], inboxes: [] as Json[], members: [] as Json[] };

    const sandboxFiles: Record<string, string> = {
        '/workspace/notes.md': '# Wirefern\n\nRetries stop after the first failure since Friday.\n',
        '/workspace/repo/app/retries/worker.py': 'MAX_ATTEMPTS = 5\n\n\ndef retry(job):\n    for attempt in range(MAX_ATTEMPTS):\n        if job.run():\n            return True\n    return False\n',
        '/workspace/repo/tests/test_retries.py': 'from app.retries.worker import retry\n\n\ndef test_dashboard_connection_retries_five_times():\n    assert retry\n',
        '/workspace/repo/README.md': '# wirefern\n\nWebhooks for WhatsApp.\n',
        '/workspace/.env': 'WIREFERN_ADMIN_KEY=[redacted]\nDEPLOY_TOKEN=[redacted]\n',
    };

    const workspaceFile = (path: string, size: number, at: string) => ({ object: 'workspace_file', path, size_bytes: size, modified_at: at, url: `https://api.noclick.test/agent/workspace/file?token=${encodeURIComponent(path)}` });
    const workspaces = new Map<string, Json[]>([
        [
            id(1),
            [
                workspaceFile('inbox/priya-3f9c2a/2026-11-10_0957_photo.jpg', 1_677_722, ago(3 * MIN)),
                workspaceFile('inbox/priya-3f9c2a/2026-11-09_1840_document_order-sheet.pdf', 220_000, ago(15 * 60 * MIN)),
                workspaceFile('inbox/bakers-group-07d1e4/2026-11-10_0912_photo.jpg', 2_202_010, ago(48 * MIN)),
                workspaceFile('made/saturday-orders.xlsx', 18_000, ago(2 * MIN)),
                workspaceFile('notes/MEMORY.md', 4_000, ago(MIN)),
                workspaceFile('added/price-list.pdf', 96_000, ago(3 * 24 * 60 * MIN)),
            ],
        ],
    ]);

    const routes = (method: string, path: string, query: URLSearchParams, body: Json): Response => {
        const failing = fails.findIndex((f) => f.method === method && f.path === path);
        if (failing >= 0) {
            const [f] = fails.splice(failing, 1);
            return json({ error: { type: f.status === 409 ? 'conflict' : 'invalid_request', message: f.message } }, f.status);
        }
        if (method === 'GET' && path === '/v1/agents') return list(agents);
        if (method === 'GET' && path === '/v1/agents/states') return json({ object: 'list', data: states, read_at: new Date(clock).toISOString() });
        if (method === 'POST' && path === '/v1/agents') {
            if (body.machine_id && !machinesEnabled.value) return notOnMachines();
            const n = agents.length + 1;
            const agent: Json = { ...agents[0], ...body, id: id(n), role: firstSentence(String(body.instructions ?? '')), status: 'idle', running_turns: 0, last_active_at: new Date(clock).toISOString(), machine_id: body.machine_id ?? null, budget_usd_per_month: body.budget_usd_per_month ?? null, model_connection: body.model_connection ?? null, triggers: undefined, former_names: [] };
            agents.unshift(agent);
            states.unshift({ agent_id: agent.id, name: agent.name, harness: agent.harness, state: 'idle', conversation: null, now: null, waiting: { asks: 0, held_calls: 0, requests: 0, total: 0 }, turn_started_at: null, last_active_at: new Date(clock).toISOString(), failed: null, waking: null });
            triggers.set(String(agent.id), ((body.triggers as Json[] | undefined) ?? []).map((t, i) => ({ id: `t-new-${i}`, kind: t.kind, spec: t, status: 'active', url: null, next_run: null, last_fired_at: null, error: null, created_at: new Date(clock).toISOString() })));
            return json(agent, 201);
        }
        if (method === 'GET' && path === '/v1/harnesses') return list(HARNESSES);
        const models = path.match(/^\/v1\/harnesses\/([^/]+)\/models$/);
        if (models && method === 'GET') {
            const q = query.get('q')?.toLowerCase();
            const route = (id: string) => (/^(openrouter|opencode|opencode-go)\//.exec(id)?.[1] ?? 'maker');
            return list((MODELS[models[1]] ?? []).filter((m) => !q || JSON.stringify(m).toLowerCase().includes(q)).map((m) => ({ object: 'harness_model', canonical: m.id, route: route(String(m.id)), ...m })));
        }
        if (method === 'GET' && path === '/v1/connections')
            return list(
                [
                    ...held.map((k, i) => ({ object: 'connection', id: `conn-${i}`, user_id: null, origin: 'api', created_at: ago(MIN), moved_from: options.moved === true && k === 'claude' ? { ...MOVED, to: { model: 'anthropic' } } : null, ...MODEL_CONNECTIONS[k] })),
                    { object: 'connection', id: 'credential:c-gh', name: 'github', integration: 'github', credential_type: 'github_oauth', status: 'connected', user_id: null, origin: 'app' },
                    { object: 'connection', id: 'credential:c-wa', name: 'whatsapp', integration: 'whatsapp', credential_type: 'whatsapp_qr', status: 'connected', user_id: null, origin: 'app' },
                    ...created.connections,
                ].filter((c) => !deletedConnections.has(String((c as Json).name)) && !deletedConnections.has(String((c as Json).id)))
            );
        const connection = path.match(/^\/v1\/connections\/([^/]+)$/);
        if (connection && method === 'DELETE') {
            deletedConnections.add(decodeURIComponent(connection[1]));
            return new Response(null, { status: 204 });
        }
        if (method === 'GET' && path === '/v1/secrets') return list(secrets);
        const secret = path.match(/^\/v1\/secrets\/([^/]+)$/);
        if (secret && method === 'DELETE') {
            const holders = agents.filter((a) => ((a.secret_ids as string[]) ?? []).includes(secret[1]));
            if (holders.length) return json({ error: { type: 'conflict', message: `${holders.map((a) => a.name).join(', ')} still lists it.` } }, 409);
            secrets.splice(secrets.findIndex((x) => x.id === secret[1]), 1);
            return new Response(null, { status: 204 });
        }
        if (method === 'POST' && path === '/v1/delete_previews' && String(body.path).startsWith('/v1/agents/')) {
            // As the platform words it (agents/__init__.py's deletion, the trash's undo).
            const named = agents.find((a) => a.id === String(body.path).split('/').at(-1));
            return json({ object: 'delete_preview', impact: { deletes: `Moves the agent ${named?.name} to the trash: it takes no more turns, its pending wake-ups and running jobs are canceled, and the card it pays with goes back to no agent.`, depends_on_it: [], data_lost: [], stops_billing: [], reversible: true, undo: 'Restorable from the trash for 30 days.' } });
        }
        const restoring = path.match(/^\/v1\/trash\/([^/]+)\/restore$/);
        if (restoring && method === 'POST') {
            const back = trash.get(restoring[1]);
            if (!back) return notFound('Nothing in the trash has that id.');
            trash.delete(restoring[1]);
            agents.splice(back.at, 0, back.agent);
            states.splice(back.at, 0, back.state);
            return json(back.agent);
        }
        if (method === 'POST' && path === '/v1/delete_previews') {
            const id = String(body.path).split('/').at(-1);
            const named = secrets.find((x) => x.id === id);
            // As the platform words it (secrets/service.py deletion, moves/carry.py derived_sign_ins).
            const readers = agents.filter((a) => ((a.secret_ids as string[]) ?? []).includes(String(id))).map((a) => `The agent '${a.name}' has it in its environment: it no longer does.`);
            const logins = id === SEC.linear ? ["The sign-in for linear, made of its value: it's revoked too."] : [];
            return json({ object: 'delete_preview', impact: { deletes: `Deletes the secret ${named?.name} for good.`, depends_on_it: [...readers, ...logins], data_lost: [], reversible: false } });
        }
        if (method === 'GET' && path === '/v1/integrations') return list(INTEGRATIONS.filter((i) => !query.get('kind') || i.kind === query.get('kind')));
        const events = path.match(/^\/v1\/integrations\/([^/]+)\/events$/);
        if (events && method === 'GET') return list(EVENTS[events[1]] ?? []);
        const joins = path.match(/^\/v1\/channels\/([^/]+)\/members$/);
        if (joins && method === 'POST') {
            const ch = channels.find((c) => c.id === joins[1]);
            if (!ch) return notFound('No channel by that id');
            const member = { type: 'agent', ...body };
            (ch.members as Json[]).push(member);
            return json(member, 201);
        }
        if (method === 'GET' && path === '/v1/channels') return list(channels.filter((c) => !query.get('agent_id') || (c.members as Json[]).some((m) => m.agent_id === query.get('agent_id'))));
        if (method === 'GET' && path === '/v1/workspaces') return list([{ object: 'workspace', id: SPACE_ID, name: 'NoClick', status: 'active', members: agents.map((a) => ({ type: 'agent', agent_id: a.id, name: a.name })), channel_count: 2, created_at: ago(MIN) }]);
        if (method === 'GET' && path === '/v1/operations') {
            const wanted = query.get('status')?.split(',');
            const live = (o: Json) => !['succeeded', 'failed', 'canceled', 'expired'].includes(String(o.status));
            return list(operations.filter((o) => (!query.get('agent_id') || o.agent_id === query.get('agent_id')) && (!wanted || wanted.includes(String(o.status)) || (wanted.includes('live') && live(o)))));
        }
        const cancel = path.match(/^\/v1\/operations\/([^/]+)\/cancel$/);
        if (cancel && method === 'POST') {
            const op = operations.find((o) => o.id === cancel[1]);
            if (!op) return notFound('No such operation.');
            op.status = 'canceled';
            return json(op);
        }
        // What each agent spent this month: one agent's, or every agent's as a line each (and a budgeted one's in the limits).
        const spentBy = (agentId: string | null) => [3.8, 6.1, 2.4, 10, 0][agents.findIndex((a) => a.id === agentId)] ?? 0;
        if (method === 'GET' && path === '/v1/usage/series') {
            const lines = query.get('group_by') === 'agent' ? agents.map((a) => ({ id: a.id, label: a.name, total_usd: spentBy(String(a.id)), events: 1, points: [] })) : [];
            return json({ object: 'usage_series', interval: 'day', from: ago(10 * 24 * 60 * MIN), to: ago(0), total_usd: spentBy(query.get('agent_id')), series: lines });
        }
        if (method === 'GET' && path === '/v1/usage/limits') {
            const budgeted = agents.filter((a) => a.budget_usd_per_month != null);
            const limits = budgeted.map((a) => ({ id: a.id, name: a.name, budget: a.budget_usd_per_month, spent: spentBy(String(a.id)), subtree_spent: spentBy(String(a.id)) }));
            return json({ period_start: ago(10 * 24 * 60 * MIN), resets_at: ago(-20 * 24 * 60 * MIN), keys: [], users: [], agents: limits, projects: [] });
        }
        // The account's skills and named memories, each naming the agents that attach it (Wirefern).
        const attached = [{ id: id(1), name: 'Wirefern' }];
        if (method === 'GET' && path === '/v1/skills')
            return list([
                { object: 'skill', id: 'sk-1', name: 'release-notes', description: 'Writes release notes from merged pull requests', version: 3, attached_to: attached.map((a) => ({ ...a, pin: null })) },
                { object: 'skill', id: 'sk-2', name: 'webhook-debugging', description: 'Finds why a webhook stopped delivering', version: 1, attached_to: attached.map((a) => ({ ...a, pin: null })) },
            ]);
        if (method === 'GET' && path === '/v1/memories') return list([{ object: 'memory', id: 'mem-team', name: 'team', description: 'What the team agreed', agent_id: null, attached_to: attached.map((a) => ({ ...a, writes: true })) }]);
        if (method === 'GET' && path === '/v1/machines')
            return json({
                object: 'list',
                data: machines.filter((m) => !query.get('kind') || m.kind === query.get('kind')).map((m) => ({ ...m, agents_enabled: machinesEnabled.value })),
                next_cursor: null,
                agents_enabled: machinesEnabled.value,
            });
        const machineCall =
            machineRoutes({ machines, stock, vetting, id: () => `m-new-${++made}`, now: () => new Date(clock).toISOString() }, method, path, query, body) ??
            machineWorldRoutes({ machines, agents, vetting, disks, now: () => clock }, method, path, query, body);
        if (machineCall) return machineCall;
        if (method === 'POST' && path === '/v1/machines/own') {
            if (!machinesEnabled.value) return notOnMachines();
            // Named by the box once it pairs, as the API does for one added without a name.
            const own = { object: 'machine', id: `m-own-${++made}`, name: `machine-${made}`, kind: 'own', status: 'provisioning', size: null, region: null, os: null, hostname: null, cpu: null, memory_gb: null, disk_gb: null, monthly_usd: 0, conversations_at_once: null, agent_share: body.agent_share ?? 0.75, agent_share_fixed: false, ...appTestingOf(body, 'ask_first'), created_at: new Date(clock).toISOString(), pairing: pairingFor('nc_mach_test') };
            machines.push(own);
            return json(own, 201);
        }
        const machine = path.match(/^\/v1\/machines\/([^/]+)$/);
        if (machine && method === 'PATCH') {
            const m = machines.find((x) => x.id === machine[1]);
            if (!m) return notFound(`No machine ${machine[1]}`);
            // What its agents use of a computer of yours: null goes back to three quarters.
            if ('agent_share' in body) m.agent_share = body.agent_share ?? 0.75;
            if ('app_testing' in body || 'docker' in body) Object.assign(m, appTestingOf(body, m.app_testing as string));
            return json({ ...m, pairing: m.pairing ? { ...(m.pairing as Json), code: null, command: null, commands: null } : null });
        }
        if (machine && method === 'GET') return json({ ...(machines.find((m) => m.id === machine[1]) ?? {}), pairing: { ...((machines.find((m) => m.id === machine[1])?.pairing as Json | null) ?? {}), code: null, command: null, commands: null } });
        const newCode = path.match(/^\/v1\/machines\/([^/]+)\/pairing_code$/);
        if (newCode && method === 'POST') {
            const m = machines.find((x) => x.id === newCode[1])!;
            m.pairing = pairingFor(`nc_mach_test${++made}`);
            return json(m);
        }

        if (method === 'POST' && path === '/v1/agents/moves') {
            move = { object: 'agent_move', id: `mv-${++made}`, prompt: `Move this session to NoClick: read https://noclick.com/move.md and follow it. Your move code is nc_move_${made}abc (it works once, for 30 minutes).`, code: `nc_move_${made}abc`, guide_url: 'https://noclick.com/move.md', expires_at: new Date(clock + 30 * MIN).toISOString(), status: 'waiting', source: null, arrived: {}, steps: [], agent_id: null, conversation: null, error: null, workspace_id: body.workspace_id ?? null };
            return json(move, 201);
        }
        const CARRIED_BEFORE = [
            { name: 'ANTHROPIC_API_KEY', to: { model: 'anthropic' }, connection: 'claude', reused: false },
            { name: 'github-token', to: { env: 'GH_TOKEN' }, secret_id: SEC.gh, key: 'GH_TOKEN', in_env: true, reused: false },
            { name: 'npmrc', to: { file: '~/.npmrc', mode: '600' }, secret_id: SEC.npm, key: 'NC_FILE_NPMRC', in_env: true, reused: false, setup: NPMRC_SETUP },
            { name: 'linear-api-key', to: {}, secret_id: SEC.linear, key: 'VALUE', in_env: false, reused: false },
            { name: 'linear', to: { tool_server: 'linear' }, credential_id: 'cred-linear', secrets: [SEC.linear] },
        ];
        const finished = () => ({
            object: 'agent_move', id: 'mv-laptop', status: 'done', source: { harness: 'claude_code', host: 'rowan-mbp', cwd: '~/code/wirefern' }, steps: [], agent_id: id(1), conversation: 'main', error: null,
            arrived: {
                files: [], skills: [], memories: [], secrets: [], consent: [], setup: [], checkout: null,
                mcp_servers: [{ name: 'notion', url: 'https://mcp.notion.test/mcp', transport: 'http', headers: [], needs_sign_in: !signedIn.notion }],
                carried: [
                    ...(options.moved === 'sign-ins' ? [] : CARRIED_BEFORE),
                    // A tool server the laptop signed in to in a browser: the person signs in again here.
                    { name: 'notion', to: { tool_server: 'notion' }, url: 'https://mcp.notion.test/mcp', step: 'mcp_notion', reused: false, needs_sign_in: !signedIn.notion, ...(signedIn.notion ? { credential_id: signedIn.notion } : {}) },
                ],
            },
        });
        if (method === 'GET' && path === '/v1/agents/moves/mv-laptop' && options.moved) return json(finished());
        const signIn = path.match(/^\/v1\/agents\/moves\/mv-laptop\/sign_ins\/([^/]+)$/);
        if (signIn && method === 'POST' && options.moved) {
            if (decodeURIComponent(signIn[1]) !== 'notion') return notFound('No tool server by that name waits on a sign-in.');
            if (!String(body.credential_id ?? '').startsWith('cred-')) return json({ error: { type: 'invalid_request', message: "That isn't a sign-in to this server.", field: 'credential_id' } }, 400);
            signedIn.notion = String(body.credential_id);
            return json(finished());
        }
        const moving = path.match(/^\/v1\/agents\/moves\/([^/]+)(\/cancel)?$/);
        if (moving) {
            if (!move || move.id !== moving[1]) return notFound('No such move.');
            if (moving[2] && method === 'POST') move.status = 'canceled';
            // The prompt and its code come only with the create.
            return json({ ...move, prompt: null, code: null });
        }
        if (method === 'POST' && path === '/v1/connections') {
            // As the API makes one: waiting for its account, with the link where someone connects it.
            const row = { object: 'connection', id: `conn-new-${++made}`, name: body.name, integration: body.integration, credential_type: body.credential_type ?? null, status: 'pending', user_id: null, origin: 'api', account: null, connect_link: { id: `link-${made}`, url: `https://noclick.test/connect/${body.name}`, expires_at: null, operation_id: `op-link-${made}` }, created_at: new Date(clock).toISOString() };
            created.connections.push(row);
            return json(row, 201);
        }
        if (method === 'POST' && path === '/v1/inboxes') {
            const row = { object: 'inbox', id: `ib-${++made}`, name: body.name, agent_id: body.agent_id ?? null, address: `${body.name}@noclick.email` };
            created.inboxes.push(row);
            return json(row, 201);
        }
        if (method === 'GET' && path === `/v1/workspaces/${SPACE_ID}/noclick` && options.spaceNoClick) return json({ agent_id: SPACE_NOCLICK_ID, label: 'NoClick · NoClick' });
        const space = path.match(/^\/v1\/workspaces\/([^/]+)(\/members)?$/);
        if (space && method === 'GET' && !space[2]) return json({ object: 'workspace', id: space[1], name: 'NoClick', status: 'active', members: [], channel_count: 2, created_at: ago(MIN) });
        if (space && method === 'POST' && space[2]) {
            created.members.push({ workspace: space[1], ...body });
            return json({ object: 'workspace_member', id: `wm-${++made}`, type: 'agent', agent_id: body.agent_id, name: null }, 201);
        }
        const agentPath = path.match(/^\/v1\/agents\/([^/]+)(\/.*)?$/);
        if (!agentPath) return notFound(`No route for ${method} ${path}`);
        const [, agentId, rest = ''] = agentPath;
        const agent = agents.find((a) => a.id === agentId);
        if (!agent) return notFound(`No agent ${agentId}.`);
        // A single read carries what was added to its workflow in the app (its MCP servers among them).
        if (rest === '' && method === 'GET') return json(agentId === id(1) ? { ...agent, added_in_app: [{ id: 'mcp-1', name: 'GitHub MCP', type: 'mcp-server', operation: null, role: 'tool' }, { id: 'n-2', name: 'Slack', type: 'automation-slack', operation: 'send_message', role: 'tool' }] } : agent);
        if (rest === '' && method === 'PATCH') {
            const refused = renameRefused(agents, agent, body);
            return refused ?? json(Object.assign(agent, body));
        }
        if (rest === '/tool_access' && method === 'GET') return json(toolAccessOf(agent));
        // To the trash, as DELETE /v1/agents/{id} answers.
        if (rest === '' && method === 'DELETE') {
            const at = agents.indexOf(agent);
            agents.splice(at, 1);
            const [state] = states.splice(states.findIndex((x) => x.agent_id === agentId), 1);
            trash.set(`tr-${agentId}`, { agent, state, at });
            const entry = { object: 'trash_item', id: `tr-${agentId}`, kind: 'agent', resource_id: agentId, name: agent.name, trashed_at: new Date(clock).toISOString(), purge_after: new Date(clock + 30 * 24 * 60 * MIN).toISOString() };
            return json({ object: 'agent', id: agentId, deleted: true, trash: entry, restorable_until: entry.purge_after, operation_id: null });
        }
        if (rest === '/conversations' && method === 'GET') return list((CONVERSATIONS[agentId] ?? ['main']).map((c, i) => ({ object: 'conversation', conversation: c, title: null, archived: false, last_activity: ago(MIN), active: i === 0 })));
        if (rest === '/workspace' && method === 'GET') return list(workspaces.get(agentId) ?? []);
        if (rest === '/workspace/files' && (method === 'PUT' || method === 'DELETE')) {
            const at = (query.get('path') ?? '').replace(/^\/+/, '');
            const kept = (workspaces.get(agentId) ?? []).filter((f) => f.path !== at);
            if (method === 'DELETE') {
                workspaces.set(agentId, kept);
                return json({ object: 'workspace_file', path: at, deleted: true });
            }
            const made = workspaceFile(at, Number(body.size_bytes ?? 0), new Date(clock).toISOString());
            workspaces.set(agentId, [made, ...kept]);
            return json(made);
        }
        if (rest === '/pause' && method === 'POST') return json(Object.assign(agent, { paused: true }));
        if (rest === '/resume' && method === 'POST') return json(Object.assign(agent, { paused: false }));
        if (rest === '/triggers' && method === 'GET') return list((triggers.get(agentId) ?? []).map((t) => viewOf(agentId, t)));
        if (rest === '/triggers' && method === 'POST') {
            const tid = `t-added-${++made}`;
            const row = { id: tid, kind: body.kind, spec: body, status: 'active', url: body.kind === 'webhook' ? `https://hooks.noclick.test/${tid}` : null, next_run: null, last_fired_at: null, error: null, created_at: new Date(clock).toISOString() };
            triggers.set(agentId, [...(triggers.get(agentId) ?? []), row]);
            return json(viewOf(agentId, row), 201);
        }
        const trigger = rest.match(/^\/triggers\/([^/]+)(\/pause|\/resume|\/test)?$/);
        if (trigger) {
            const rows = triggers.get(agentId) ?? [];
            const row = rows.find((t) => t.id === trigger[1]);
            if (!row) return notFound('No trigger by that id');
            const to = trigger[2];
            if (!to && method === 'DELETE') {
                triggers.set(agentId, rows.filter((t) => t !== row));
                return new Response(null, { status: 204 });
            }
            if (!to && method === 'PATCH') {
                const spec = row.spec as Json;
                for (const k of ['cron', 'tz', 'message', 'conversation', 'filters', 'mode']) if (k in body) spec[k] = body[k];
                return json(viewOf(agentId, row));
            }
            if (to === '/pause' && method === 'POST') return json(viewOf(agentId, Object.assign(row, { paused: true })));
            if (to === '/resume' && method === 'POST') return json(viewOf(agentId, Object.assign(row, { paused: false, stopped: false, error: null, fix: null })));
            if (to === '/test' && method === 'POST')
                return json({ object: 'operation', id: `op-test-${++made}`, kind: 'agent.rehearse', status: 'succeeded', agent_id: agentId, result: { reply: 'I’d check last night’s failed deliveries and post what I found.', tool_calls: [], transcript: [], scenario: null, sample: body.sample ?? null }, error: null, created_at: new Date(clock).toISOString(), updated_at: new Date(clock).toISOString() }, 202);
        }
        if (rest === '/wakeups' && method === 'GET') return list(wakeups.filter((w) => w.agent_id === agentId && w.status === 'pending'));
        const wakeup = rest.match(/^\/wakeups\/([^/]+)\/cancel$/);
        if (wakeup && method === 'POST') {
            const w = wakeups.find((x) => x.id === wakeup[1] && x.agent_id === agentId);
            if (!w) return notFound('No wake-up by that id');
            return json(Object.assign(w, { status: 'canceled' }));
        }
        if (rest === '/attachments' && method === 'POST') return json({ object: 'attachment', id: `att-${++made}`, name: query.get('name'), mime_type: query.get('mime_type'), size_bytes: 12, url: `https://files.test/${query.get('name')}` }, 201);
        if (rest === '/messages' && method === 'POST') return json({ object: 'operation', id: `op-new-${++made}`, kind: 'agent.message', status: 'queued', agent_id: agentId, created_at: new Date(clock).toISOString(), updated_at: new Date(clock).toISOString() }, 202);
        const conversation = rest.match(/^\/conversations\/([^/]+)(\/.*)?$/);
        if (conversation) {
            const [, c, tail = ''] = conversation;
            if (tail === '' && method === 'PATCH') return json({ object: 'conversation_settings', permission_mode: body.permission_mode, effective_permission_mode: body.permission_mode, permission_modes: ['approval-required', 'auto-accept-edits', 'auto', 'full-access'], not_supported: {} });
            const servers = toolServers.get(`${agentId}/${decodeURIComponent(c)}`) ?? { object: 'tool_servers', data: [], source: 'none', checked_at: null, reconnect: { available: false, scope: null, why: null } };
            if (tail === '/tool_servers' && method === 'GET') return json(servers);
            const reconnect = tail.match(/^\/tool_servers\/([^/]+)\/reconnect$/);
            if (reconnect && method === 'POST') {
                const named = (servers.data as Json[]).find((x) => x.name === decodeURIComponent(reconnect[1]));
                if (!named) return notFound('No tool server by that name');
                Object.assign(named, { status: 'connected', tool_count: 12, error: null });
                return json(servers);
            }
            if (tail === '/sandbox' && method === 'GET')
                return json({ agent_id: agentId, conversation: decodeURIComponent(c), harness: agent.harness, place: agent.machine_id ? 'machine' : 'sandbox', status: options.sandbox ?? 'running', started_at: (options.sandbox ?? 'running') === 'running' ? ago(4 * MIN) : null, cpu: 2, memory_mb: 4096, region: 'us-east', usd_per_hour: 0.19, spent_usd_today: 0.07, machine_id: agent.machine_id, project_id: null, workspace: '/workspace' });
            if (tail === '/sandbox/files' && method === 'GET') {
                const at = query.get('path') ?? '/workspace';
                if (query.get('view') === 'list') {
                    const prefix = at.replace(/\/$/, '');
                    const entries = new Map<string, Json>();
                    for (const [p, text] of Object.entries(sandboxFiles)) {
                        if (!p.startsWith(`${prefix}/`)) continue;
                        const parts = p.slice(prefix.length + 1).split('/');
                        if (query.get('recursive') === 'true' || parts.length === 1) entries.set(p, { path: p, type: 'file', size: text.length, updated_at: ago(MIN) });
                        else entries.set(`${prefix}/${parts[0]}`, { path: `${prefix}/${parts[0]}`, type: 'directory', size: null, updated_at: ago(MIN) });
                    }
                    return json({ object: 'list', data: [...entries.values()], next_cursor: null, source: options.sandbox === 'stopped' ? 'workspace' : 'sandbox' });
                }
                const text = sandboxFiles[at];
                return text === undefined ? notFound(`No file ${at}.`) : new Response(text, { status: 200, headers: { 'Content-Type': 'application/octet-stream' } });
            }
            if (tail === '/sandbox/shell' && method === 'POST') return json({ agent_id: agentId, conversation: c, url: 'wss://api.noclick.test/v1/terminals/attach', token: 'shell-token', token_expires_at: ago(-2 * MIN), idle_limit_s: 900 });
            if (tail === '' && method === 'GET')
                return json({
                    object: 'conversation', id: c, agent_id: agentId,
                    messages: [
                        { role: 'user', text: 'Webhook retries stop after the first failure since Friday. Can you find out why?', created_at: ago(30 * MIN) },
                        {
                            role: 'assistant', text: 'Found it and fixed it.', created_at: ago(20 * MIN), operation_id: 'op-2',
                            tool_calls: [
                                { source: 'harness', id: 's1', kind: 'edit', tool: 'Edit', path: '/workspace/repo/app/retries/worker.py', diffs: [{ path: '/workspace/repo/app/retries/worker.py', kind: 'update', diff: '--- a/app/retries/worker.py\n+++ b/app/retries/worker.py\n@@ -1 +1 @@\n-MAX_ATTEMPTS = 1\n+MAX_ATTEMPTS = 5\n' }], created_at: ago(22 * MIN) },
                                { source: 'harness', id: 's2', kind: 'edit', tool: 'Write', path: '/workspace/repo/tests/test_retries.py', diffs: [{ path: '/workspace/repo/tests/test_retries.py', kind: 'add', diff: '--- /dev/null\n+++ b/tests/test_retries.py\n@@ -0,0 +1,5 @@\n+from app.retries.worker import retry\n+\n+\n+def test_dashboard_connection_retries_five_times():\n+    assert retry\n' }], created_at: ago(21 * MIN) },
                            ],
                        },
                    ],
                });
        }
        return notFound(`No route for ${method} ${path}`);
    };

    const fetch: typeof window.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const raw = init?.body;
        // A file's bytes are said by their size.
        const body = (typeof raw === 'string' && raw ? JSON.parse(raw) : raw instanceof Uint8Array ? { size_bytes: raw.byteLength } : raw instanceof Blob ? { size_bytes: raw.size } : {}) as Json;
        requests.push({ method, path: url.pathname, query: url.searchParams, body });
        // A test's latency: the request answers once this settles, as it stands then.
        await options.answerAfter?.(method, url.pathname, url.searchParams);
        return routes(method, url.pathname, url.searchParams, body);
    };

    return {
        client: workFixtureClient(fetch),
        fetch,
        requests,
        agents,
        states,
        triggers,
        operations,
        setState: (agentId, change) => Object.assign(states.find((s) => s.agent_id === agentId)!, change),
        failNext: (method, path, status = 400, message = 'Refused.') => fails.push({ method, path, status, message }),
        signIn: (name, account) => Object.assign(created.connections.find((c) => c.name === name)!, { status: 'connected', account, connect_link: null }),
        addAppAccount: (credentialId, name, integration, credentialType, account) =>
            created.connections.push({ object: 'connection', id: `credential:${credentialId}`, name, integration, credential_type: credentialType, status: 'connected', user_id: null, origin: 'app', account: account ?? null, connect_link: null, created_at: new Date(clock).toISOString() }),
        created,
        machines,
        toolServers,
        machinesEnabled,
        stock,
        vetting,
        disks,
        secrets,
        workspaces,
        moveTo: (change) => Object.assign(move!, change),
    };
}
