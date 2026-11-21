// Connections' made-up world: one made-up account's connected accounts (its own, its workspace's, one shared with it;
// working, broken, revoked, moved), what each provider says when asked about it and what uses it, and the platform API
// answering for them as it does (`GET /v1/connections` and each account's view, its check, rename and delete, a connect
// link, and the integrations catalog). The lab (../lab) and the tests open the page over it; a scene changes what it
// needs of it (`ConnectionsWorld`).
import type { ConnectionCheck } from '@/lib/connectionCheck';
import { refusedToAccountKey } from '@/screens/console/ownerOnly';
import type { WorkflowRef } from '@/screens/resources/files';
import type { AccountCredential } from '../model';

/** The fixtures' moment: every date in them reads against it. */
export const CLOCK = '2026-11-20T12:00:00.000Z';

/** The team workspace the account is in. */
export const TEAM = 'org_northwind';

const ADDED = '2026-11-03T09:30:00Z';

/** Each account's integration and its app as the API names it, by the account's id. */
const INTEGRATIONS = new Map<string, { integration: string; app: string }>();

/** An account as the connect form names it when you don't (its app and the day), unless `fields` names it. */
function account(id: string, credential_type: string, integration: string, app: string, fields: Partial<AccountCredential> = {}): AccountCredential {
    INTEGRATIONS.set(id, { integration, app });
    return { id, name: `${app} - 11/3/2026`, credential_type, metadata: {}, created_at: ADDED, updated_at: ADDED, access_type: 'owner', ...fields };
}

/** The account's connected accounts, by id. */
export const ACCOUNTS = {
    gmail: account('cred_gmail', 'google_gmail_oauth', 'gmail', 'Gmail', { metadata: { email: 'maya@northwind.test' } }),
    gmailOps: account('cred_gmail_ops', 'google_gmail_oauth', 'gmail', 'Gmail', { name: 'Gmail - 11/5/2026', metadata: { email: 'ops@northwind.test' }, created_at: '2026-11-05T09:30:00Z' }),
    github: account('cred_github', 'github_oauth', 'github', 'GitHub', { metadata: { login: 'maya-n' } }),
    releaseBot: account('cred_github_pat', 'github_pat', 'github', 'GitHub', { name: 'Release bot' }),
    slack: account('cred_slack', 'slack_oauth', 'slack', 'Slack', { metadata: { email: 'maya@northwind.test' }, revoked_at: '2026-11-18T07:00:00Z' }),
    discord: account('cred_discord', 'discord_bot_install', 'discord', 'Discord', {
        name: 'Northwind server',
        connection_healthy: false,
        connection_hint: 'The bot was removed from the server. Add it again.',
    }),
    whatsapp: account('cred_whatsapp', 'whatsapp_qr', 'whatsapp', 'WhatsApp', { name: 'WhatsApp (+12025550101)', metadata: { phone_number: '+12025550101' } }),
    linear: account('cred_linear', 'linear_pat', 'linear', 'Linear', {
        name: 'Linear',
        metadata: { moved_from: { move_id: 'mov_studio', host: 'studio-mbp', folder: '~/code/studio', at: '2026-11-08T10:00:00Z' } },
    }),
    stripe: account('cred_stripe', 'stripe_api_key', 'stripe', 'Stripe', { name: 'Stripe live' }),
    anthropic: account('cred_anthropic', 'agent_anthropic', 'anthropic', 'Anthropic', { name: 'Anthropic key' }),
    claudePlan: account('cred_claude_plan', 'agent_claude_code_oauth', 'anthropic', 'Claude', { name: 'Claude (Claude Code)' }),
    notion: account('cred_notion', 'notion_oauth', 'notion', 'Notion', {
        access_type: 'shared',
        shared_by_name: 'Priya Raman',
        shared_by_email: 'priya@northwind.test',
        metadata: { email: 'docs@northwind.test' },
    }),
    hubspot: account('cred_hubspot', 'hubspot_oauth', 'hubspot', 'HubSpot', { access_type: 'shared_org', organization_id: TEAM, metadata: { email: 'sales@northwind.test' } }),
    sheets: account('cred_sheets', 'google_sheets_oauth', 'google_sheets', 'Google Sheets', { access_type: 'shared_org', organization_id: TEAM, metadata: { email: 'finance@northwind.test' } }),
} satisfies Record<string, AccountCredential>;

export type AccountId = keyof typeof ACCOUNTS;

/** What a provider says when asked: its answer, the check failing (a rate limit), or no answer yet. */
export type ProbeAnswer = ConnectionCheck | 'failed' | 'waiting';

/** What each provider says about its account: its own things where it has any. */
export const PROBES: Record<string, ProbeAnswer> = {
    cred_gmail: { reachable: true, samples: [{ label: 'Clients' }, { label: 'Invoices' }, { label: 'Hiring' }], total: 14, noun: 'labels', account_label: 'maya@northwind.test' },
    cred_gmail_ops: { reachable: true, samples: [{ label: 'Support' }, { label: 'Refunds' }], noun: 'labels', account_label: 'ops@northwind.test' },
    cred_github: {
        reachable: true,
        samples: [{ label: 'northwind/site' }, { label: 'northwind/api' }, { label: 'northwind/infra' }],
        total: 23,
        noun: 'repositories',
        account_label: 'maya-n',
    },
    cred_github_pat: { reachable: true, samples: [{ label: 'northwind/site' }], noun: 'repositories', account_label: 'northwind-release-bot' },
    cred_discord: { reachable: false, error: 'Unknown Guild (10004)', hint: 'Discord no longer lets NoClick into this server. Add the bot again.' },
    cred_whatsapp: { reachable: true, samples: [], account_label: '+1 202-555-0101' },
    cred_linear: { reachable: true, samples: [{ label: 'Platform' }, { label: 'Growth' }], noun: 'teams', account_label: 'maya@northwind.test' },
    cred_stripe: { reachable: true, samples: [], proves: 'reachability' },
    cred_notion: { reachable: true, samples: [{ label: 'Handbook' }, { label: 'Roadmap' }, { label: 'Meeting notes' }], noun: 'pages' },
    cred_hubspot: { reachable: true, samples: [], account_label: 'sales@northwind.test' },
    cred_sheets: { reachable: null },
};

/** The automations that use each account. */
export const USED_BY: Record<string, WorkflowRef[]> = {
    cred_gmail: [
        { id: 'wf_triage', name: 'Inbox triage', marks: ['automation-gmail', 'agent'] },
        { id: 'wf_invoices', name: 'Invoices to Sheets', marks: ['automation-gmail', 'automation-google-sheets'] },
    ],
    cred_github: [{ id: 'wf_release', name: 'Release notes', marks: ['automation-github-rest', 'automation-slack'] }],
    cred_slack: [{ id: 'wf_release', name: 'Release notes', marks: ['automation-github-rest', 'automation-slack'] }],
    cred_hubspot: [{ id: 'wf_leads', name: 'New leads to HubSpot', marks: ['automation-hubspot'] }],
};

type Json = Record<string, unknown>;

/** An integration in the catalog, as `GET /v1/integrations` lists it. */
function integration(name: string, label: string, kind: 'app' | 'model', credentialTypes: string[], connectWith: string[], subscription = false): Json {
    return {
        name,
        label,
        kind,
        subscription,
        connect_with: connectWith,
        operation_count: kind === 'app' ? 12 : null,
        account_free_operation_count: 0,
        credential_types: credentialTypes,
        events: [],
    };
}

/** The catalog: the apps whose accounts connect here, and the model providers agents think with. */
export const INTEGRATIONS_CATALOG: readonly Json[] = [
    integration('gmail', 'Gmail', 'app', ['google_gmail_oauth'], ['oauth']),
    integration('slack', 'Slack', 'app', ['slack_oauth'], ['oauth']),
    integration('github', 'GitHub', 'app', ['github_oauth', 'github_pat'], ['oauth', 'key']),
    integration('google_calendar', 'Google Calendar', 'app', ['google_calendar_oauth'], ['oauth']),
    integration('notion', 'Notion', 'app', ['notion_oauth'], ['oauth']),
    integration('google_sheets', 'Google Sheets', 'app', ['google_sheets_oauth'], ['oauth']),
    integration('whatsapp', 'WhatsApp', 'app', ['whatsapp_qr'], ['qr']),
    integration('linear', 'Linear', 'app', ['linear_pat'], ['key']),
    integration('hubspot', 'HubSpot', 'app', ['hubspot_oauth'], ['oauth']),
    integration('discord', 'Discord', 'app', ['discord_bot_install'], ['oauth']),
    integration('stripe', 'Stripe', 'app', ['stripe_api_key'], ['key']),
    integration('airtable', 'Airtable', 'app', ['airtable_pat'], ['key']),
    integration('phone', 'Phone', 'app', ['phone_number'], ['purchase']),
    integration('anthropic', 'Anthropic', 'model', ['agent_anthropic', 'agent_claude_code_oauth'], ['key', 'oauth'], true),
    integration('openai', 'OpenAI', 'model', ['agent_openai', 'agent_codex_oauth'], ['key', 'oauth'], true),
    integration('openrouter', 'OpenRouter', 'model', ['agent_openrouter'], ['key']),
];

export interface ConnectionsWorld {
    /** The accounts listed (all of them when left out); `waiting` holds the list back. */
    accounts?: readonly AccountId[] | 'waiting';
    /** The team workspace the page shows (`TEAM` when left out); null for the account's own alone. */
    team?: string | null;
    /** What a provider says about an account, over its usual answer. */
    probes?: Record<string, ProbeAnswer>;
}

/** The team workspace a world shows. */
export const teamOf = (world: ConnectionsWorld): string | null => (world.team === undefined ? TEAM : world.team);

/** The accounts a world lists: in the account's own workspace, none of a team's. */
export function listed(world: ConnectionsWorld): AccountCredential[] | 'waiting' {
    if (world.accounts === 'waiting') return 'waiting';
    const all: AccountCredential[] = world.accounts ? world.accounts.map((id) => ACCOUNTS[id]) : Object.values(ACCOUNTS);
    return teamOf(world) ? all : all.filter((a) => a.access_type !== 'shared_org');
}

/** What the account goes by, as the API reads it off its credential: its login, email, who a check verified it as, else
 *  the number it links as people write it. */
function accountLine(credential: AccountCredential): string | null {
    const meta = credential.metadata ?? {};
    for (const key of ['login', 'email', 'verified_as']) {
        const value = meta[key];
        if (typeof value === 'string' && value.trim() && value.trim() !== 'unknown') return value.trim();
    }
    const phone = typeof meta.phone_number === 'string' ? /^\+1(\d{3})(\d{3})(\d{4})$/.exec(meta.phone_number) : null;
    return phone ? `+1 ${phone[1]}-${phone[2]}-${phone[3]}` : null;
}

/** What the platform API knows of an account besides itself. */
export interface ApiWorld {
    /** The accounts listed in the workspace read, or none yet. */
    accounts: () => AccountCredential[] | 'waiting';
    /** Its integration and its app as the API names it ("Slack"). */
    integrationOf: (credential: AccountCredential) => { integration: string; app: string };
    /** The team workspace read, where one is. */
    team: string | null;
    usedBy: (accountId: string) => WorkflowRef[];
    probe: (accountId: string) => ProbeAnswer;
}

/** One account connected in the app, as the API answers it. */
export function connectionView(credential: AccountCredential, world: Pick<ApiWorld, 'integrationOf' | 'team' | 'usedBy'>): Json {
    const shared = credential.access_type === 'shared' ? 'you' : credential.access_type === 'shared_org' ? 'workspace' : null;
    const healthy = credential.connection_healthy;
    const { integration: name, app } = world.integrationOf(credential);
    return {
        object: 'connection',
        id: `credential:${credential.id}`,
        name: credential.name,
        connect_link: null,
        integration: name,
        credential_type: credential.credential_type,
        status: credential.revoked_at ? 'disconnected' : 'connected',
        user_id: null,
        disconnected: credential.revoked_at
            ? { reason: 'revoked', message: `This ${app} account was disconnected.`, provider_said: null, since: credential.revoked_at, next_step: 'Reconnect it in the NoClick app.' }
            : null,
        origin: 'app',
        access: shared ? 'view' : 'owner',
        shared: shared ? { with: shared, by: { name: credential.shared_by_name ?? null, email: credential.shared_by_email ?? null } } : null,
        organization_id: world.team,
        approval_operations: [],
        test_account: false,
        moved_from: credential.metadata?.moved_from ?? null,
        account: accountLine(credential),
        plan: null,
        usage: null,
        verification: null,
        health: healthy === null || healthy === undefined ? null : { healthy, status: healthy ? 'connected' : 'failed', hint: credential.connection_hint ?? null },
        used_by: world.usedBy(credential.id).map((w) => ({ kind: 'workflow', id: w.id, name: w.name, binding: null, marks: w.marks, user_id: null })),
        connected_at: credential.created_at,
        created_at: credential.created_at,
        updated_at: credential.updated_at ?? credential.created_at,
    };
}

/** A named connection made through the API, still waiting for its account at its connect page. */
function pendingConnection(name: string, integrationName: string, credentialType: string | null): Json {
    return {
        object: 'connection',
        id: `conn_${name.replace(/[^a-z0-9]/gi, '').slice(0, 16)}`,
        name,
        connect_link: { url: `https://noclick.test/connect/${encodeURIComponent(name)}`, operation_id: `op_${name.replace(/[^a-z0-9]/gi, '')}`, expires_at: '2026-11-27T12:00:00Z' },
        integration: integrationName,
        credential_type: credentialType,
        status: 'pending',
        origin: 'api',
        access: 'owner',
        shared: null,
        organization_id: null,
        approval_operations: [],
        used_by: [],
        connected_at: null,
        created_at: CLOCK,
        updated_at: CLOCK,
    };
}

const never = () => new Promise<Response>(() => undefined);
const refused = (status: number, type: string, message: string) => Response.json({ error: { type, message } }, { status });

/** Told of every call the page makes, what it sent, and how it was answered (a test's record). */
export type Observe = (method: string, path: string, answered: Promise<Response>, body: Record<string, unknown>) => void;

/** The API's answers for `world`: its list, one account, a check, a rename, a delete, a connect link and the catalog.
 *  Acting as one of the account's keys (`key`), what the API refuses a key is refused here too. */
export function connectionsFetch(world: ApiWorld, { actsAs = 'owner', observe }: { actsAs?: 'owner' | 'key'; observe?: Observe } = {}): typeof fetch {
    const renamed = new Map<string, string>();
    const deleted = new Set<string>();
    const made = new Map<string, Json>();
    const current = (): AccountCredential[] | 'waiting' => {
        const all = world.accounts();
        if (all === 'waiting') return all;
        return all.filter((c) => !deleted.has(c.id)).map((c) => (renamed.has(c.id) ? { ...c, name: renamed.get(c.id)! } : c));
    };
    const view = (c: AccountCredential) => connectionView(c, world);
    const answer = async (method: string, url: URL, body: Json): Promise<Response> => {
        const path = decodeURIComponent(url.pathname);
        if (actsAs === 'key' && refusedToAccountKey(method, url.pathname)) return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        if (method === 'GET' && path === '/v1/integrations') {
            const kind = url.searchParams.get('kind');
            return Response.json({ object: 'list', data: INTEGRATIONS_CATALOG.filter((i) => !kind || i.kind === kind), next_cursor: null });
        }
        if (method === 'GET' && path === '/v1/connections') {
            const accounts = current();
            if (accounts === 'waiting') return never();
            return Response.json({ object: 'list', data: [...accounts.map(view), ...made.values()], next_cursor: null });
        }
        if (method === 'POST' && path === '/v1/connections') {
            const name = String(body.name);
            const connection = pendingConnection(name, String(body.integration), typeof body.credential_type === 'string' ? body.credential_type : null);
            made.set(name, connection);
            return Response.json(connection, { status: 201 });
        }
        // Its connect page finishes at once: the person connected an account there.
        const waited = /^\/v1\/operations\/(op_[^/]+)\/wait$/.exec(path);
        const finished = waited && [...made.values()].find((c) => (c.connect_link as Json | null)?.operation_id === waited[1]);
        if (waited && finished && method === 'GET') {
            made.set(String(finished.name), { ...finished, status: 'connected', connect_link: null, account: 'maya@northwind.test', connected_at: CLOCK });
            return Response.json({ object: 'operation', id: waited[1], kind: 'credential.connect', status: 'succeeded', result: { connection: finished.id }, error: null, created_at: CLOCK, updated_at: CLOCK });
        }
        const named = /^\/v1\/connections\/([^/]+)$/.exec(path);
        const found = named && [...made.values()].find((c) => c.id === named[1] || c.name === named[1]);
        if (found && method === 'GET') return Response.json(found);
        const one = /^\/v1\/connections\/credential:([^/]+)(\/verify|\/connect_links)?$/.exec(path);
        const accounts = current();
        const credential = one && accounts !== 'waiting' ? accounts.find((c) => c.id === one[1]) : undefined;
        if (!one || !credential) return refused(404, 'not_found', `The fixtures have no ${method} ${path}.`);
        if (one[2] === '/verify' && method === 'POST') {
            const probe = world.probe(credential.id);
            if (probe === 'waiting') return never();
            if (probe === 'failed') return refused(429, 'rate_limited', 'Too many checks in a minute. Try again shortly.');
            return Response.json({ ...view(credential), verification: { message: null, ...probe } });
        }
        if (one[2] === '/connect_links' && method === 'POST') {
            return Response.json({ object: 'connect_link', url: `https://noclick.test/connect/reconnect-${credential.id}`, expires_at: '2026-11-27T12:00:00Z' }, { status: 201 });
        }
        if (method === 'GET') return Response.json(view(credential));
        if (method === 'PATCH') {
            renamed.set(credential.id, String(body.name));
            return Response.json(view({ ...credential, name: renamed.get(credential.id)! }));
        }
        if (method === 'DELETE') {
            deleted.add(credential.id);
            return Response.json({ object: 'connection', id: `credential:${credential.id}`, name: credential.name, deleted: true });
        }
        return refused(405, 'invalid_request', `The fixtures have no ${method} ${path}.`);
    };
    return (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const body = init?.body ? (JSON.parse(String(init.body)) as Json) : {};
        const answered = answer(method, url, body);
        observe?.(method, decodeURIComponent(url.pathname), answered, body);
        return answered;
    };
}

/** The platform API as it answers in this world: the accounts it lists in the workspace shown, and their checks. */
export function worldFetch(world: ConnectionsWorld, options: { actsAs?: 'owner' | 'key'; observe?: Observe } = {}): typeof fetch {
    const probes = { ...PROBES, ...world.probes };
    return connectionsFetch(
        {
            accounts: () => listed(world),
            integrationOf: (credential) => {
                const known = INTEGRATIONS.get(credential.id);
                if (!known) throw new Error(`The fixtures' account ${credential.id} names no integration.`);
                return known;
            },
            team: teamOf(world),
            usedBy: (accountId) => USED_BY[accountId] ?? [],
            probe: (accountId) => probes[accountId] ?? { reachable: null },
        },
        options
    );
}
