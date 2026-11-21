// The account's own read, and the /v1 routes only its signed-in owner may call (keys, changing the account, the object
// resolver, the card onboarding session, asking for machines). The SDK has no methods for them, so they go through the
// client's request() here, typed once. A key calling an owner-only one gets 403 `permission_denied`.
//
// `GET /v1/account` answers the signed-in owner and one of the account's own secret keys acting for the account. A key
// reads a closed list of fields, the ones not marked "the owner's view only" below.
import type { CardProgramStatus, NoClick, Page } from 'noclick';

export interface AccountCounts {
    /** The owner's view only. */
    keys_active?: number;
    /** The owner's view only. */
    keys_used?: number;
    users_active: number;
    users_suspended: number;
    agents: number;
    operations_total: number;
    operations_running: number;
    operations_held: number;
    operations_failed_24h: number;
    /** The owner's view only. */
    human_requests_awaiting_you?: number;
    channels_open: number;
    sandboxes_live: number;
    inboxes: number;
    phone_numbers: number;
    /** Webhook endpoints, the account's and its users'. */
    webhooks: number;
    /** Hosted MCP servers, the account's and its users'. */
    mcp_servers: number;
    /** Designed, not built yet: counted once each kind ships. */
    apps?: number;
    databases?: number;
    buckets?: number;
    domains?: number;
    repos?: number;
    cards?: number;
    browser_profiles?: number;
    machines?: number;
    volumes?: number;
    dicts?: number;
    queues?: number;
    secrets?: number;
}

export interface AccountView {
    object: 'account';
    /** The NoClick account itself (its owner's sign-in), not one of its users. */
    id: string;
    /** The owner's view only. */
    email?: string | null;
    plan: { tier: string };
    /** `remaining_usd` null = unknown (or `unlimited`), never 0. `funds_usd` is the part of it the account added (not
     *  its plan's included usage): what a purchase, or an agent on a costly model on NoClick's key, needs. */
    balance: { remaining_usd: number | null; funds_usd?: number | null; purchase_floor_usd?: number; resets_at: string | null; unlimited?: boolean };
    month: { period_start: string; resets_at: string; spent_usd: number };
    /** The owner's view only: the account's monthly spending cap (`cap_usd` null while none is set; where one is, what
     *  its billing period spent and whether it's `reached`) and who set it last. Null when it can't be read now. */
    spend_cap?: SpendCapView | null;
    counts: AccountCounts;
    limits: {
        sandboxes_live_max: number;
        background_execs_max: number;
        inboxes_max: number;
        human_emails_per_day: number;
        human_emails_used_24h: number;
        inbox_replies_per_day: number;
        webhooks_max: number;
    };
    features: { phone_numbers: boolean };
    /** The region new sandboxes and agents take when a call names none (null: wherever NoClick has capacity). */
    default_region: string | null;
    /** What a paused user is told when `pause_spending` names no message (null: each pause says). */
    spending_paused: PausedSpendingDefault | null;
    /** The owner's view only: the key the signed-in owner's calls are billed and logged under. */
    console_key_id?: string;
    meta: {
        /** What a key with every scope (`*`) holds: what Full access is built from. */
        scopes: string[];
        /** The scopes a key holds only when it names them, never part of Full access (absent from an older server). */
        explicit_scopes?: string[];
        session_scopes: string[];
        operation_kinds: string[];
        operation_statuses: string[];
        error_types: { type: string; status: number }[];
        mcp_tools: string[];
    };
}

/** The account's monthly spending cap, as `/v1/account` and `/v1/usage/limits` answer it. */
export interface SpendCapView {
    object: 'spend_cap';
    cap_usd: number | null;
    spent_usd?: number;
    period_start?: string;
    resets_at?: string;
    reached?: boolean;
    set_by?: Record<string, unknown> | null;
}

/** The account's default for a paused user's message and button. */
export interface PausedSpendingDefault {
    message: string | null;
    action: { label: string; url: string } | null;
}

/** Something the owner made public that a publishable key may call: a shared agent's page (workflows' endpoints register the same way). */
export interface PublicEndpoint {
    object: 'public_endpoint';
    kind: string;
    id: string;
    /** Null once it stopped being public (a key still lists it). */
    name: string | null;
    url: string | null;
    user_id: string | null;
    /** On a key's view: whether it's still public. */
    public?: boolean;
}

export interface KeyView {
    object: 'key';
    id: string;
    kind: 'api' | 'console' | 'publishable';
    /** A secret key (`nk_live_`) acts for the account; a publishable one (`nk_pub_`) only calls its public endpoints. */
    type: 'secret' | 'publishable';
    name: string;
    key_prefix: string;
    scopes: string[];
    spend_cap_usd_per_month: number | null;
    user_id: string | null;
    created_at: string;
    last_used_at: string | null;
    expires_at: string | null;
    revoked_at: string | null;
    spent_usd_this_month?: number;
    /** Only on a secret key's create response; never shown again. */
    raw_key?: string;
    /** A publishable key's own: the key in full (it isn't a secret) and what it may call. */
    publishable_key?: string;
    public_endpoints?: PublicEndpoint[];
    per_visitor_limit_per_minute?: number;
    allowed_origins?: string[];
}

/** What a publishable key may call, as the create and update routes take it. */
export interface PublicAccessInput {
    public_endpoints?: { kind: string; id: string }[];
    per_visitor_limit_per_minute?: number;
    allowed_origins?: string[];
}

export interface CreateKeyInput extends PublicAccessInput {
    name: string;
    type?: 'secret' | 'publishable';
    /** A secret key's; a publishable key has none. */
    scopes?: string[];
    spend_cap_usd_per_month?: number | null;
    user_id?: string | null;
    /** ISO time in the future. */
    expires_at?: string | null;
}

/** `null` cap removes it; an absent field is left alone. */
export interface UpdateKeyInput extends PublicAccessInput {
    name?: string;
    spend_cap_usd_per_month?: number | null;
}

export type ObjectType =
    | 'operation'
    | 'agent'
    | 'user'
    | 'human_request'
    | 'connection'
    | 'credential'
    | 'channel'
    | 'inbox'
    | 'sandbox'
    | 'phone_number'
    | 'workspace'
    | 'webhook'
    | 'secret'
    | 'dict'
    | 'queue'
    | 'volume'
    | 'bucket'
    | 'mcp_server'
    | 'key'
    | 'legacy_key';

export interface ObjectRef {
    object: 'object_ref';
    type: ObjectType;
    id: string;
    user_id: string | null;
}

// Owner routes are account-level: they never carry a user header.
const account = { user: null } as const;

export function getAccount(client: NoClick, signal?: AbortSignal): Promise<AccountView> {
    return client.request<AccountView>('GET', '/v1/account', { ...account, signal });
}

/** Changes only the fields sent; `default_region: null` clears it, `spending_paused: null` the default, and
 *  `spend_cap_usd: null` the monthly spending cap (whole dollars; only the signed-in owner sets, raises or removes it). */
export function updateAccount(
    client: NoClick,
    input: { default_region?: string | null; spending_paused?: PausedSpendingDefault | null; spend_cap_usd?: number | null }
): Promise<AccountView> {
    return client.request<AccountView>('PATCH', '/v1/account', { ...account, json: input });
}

export async function listKeys(
    client: NoClick,
    options: { status?: 'active' | 'revoked' | 'all'; cursor?: string | null; limit?: number } = {}
): Promise<Page<KeyView>> {
    const page = await client.request<{ data: KeyView[]; next_cursor: string | null }>('GET', '/v1/keys', {
        ...account,
        query: { status: options.status, cursor: options.cursor, limit: options.limit },
    });
    return { data: page.data, nextCursor: page.next_cursor ?? null };
}

export const TOKEN_SCOPE = 'credentials:token';

/** Scopes a key holds only when they're named, never part of full access: those that read a secret (a provider's raw
 *  token, a card's number, a webhook's signing secret, the keys an agent's terminal shows), answering a call NoClick
 *  holds for the owner's yes, switching what it holds, accepting the machines usage policy for the company, making
 *  keys, and linking a phone number (which signs in to the account). */
export const EXPLICIT_SCOPES: readonly string[] = [
    TOKEN_SCOPE,
    'cards:reveal',
    'webhooks:reveal',
    'agents:terminal',
    'approvals:answer',
    'approvals:policy',
    'machines:vetting',
    'keys:create',
    'account:phones',
];

/** Every scope but those a key holds only by name: the default for a new key. */
export function fullAccessScopes(all: readonly string[]): string[] {
    return all.filter((s) => !EXPLICIT_SCOPES.includes(s));
}

/** The account's public endpoints, for a publishable key to list. */
export async function listPublicEndpoints(client: NoClick, signal?: AbortSignal): Promise<PublicEndpoint[]> {
    return (await client.request<{ data: PublicEndpoint[] }>('GET', '/v1/public_endpoints', { ...account, signal })).data;
}

export function createKey(client: NoClick, input: CreateKeyInput): Promise<KeyView> {
    return client.request<KeyView>('POST', '/v1/keys', { ...account, json: input });
}

export interface SetupCode {
    object: 'setup_code';
    /** Redeemed once, by POST /v1/setup, for a key of this account. */
    code: string;
    key_name: string;
    expires_at: string;
}

/** A one-time code a coding agent trades for a key that lands in its project's .env, never in its context. */
export function createSetupCode(client: NoClick): Promise<SetupCode> {
    return client.request<SetupCode>('POST', '/v1/cli/setup_codes', account);
}

export function updateKey(client: NoClick, keyId: string, input: UpdateKeyInput): Promise<KeyView> {
    return client.request<KeyView>('PATCH', `/v1/keys/${encodeURIComponent(keyId)}`, { ...account, json: input });
}

export function revokeKey(client: NoClick, keyId: string): Promise<KeyView> {
    return client.request<KeyView>('DELETE', `/v1/keys/${encodeURIComponent(keyId)}`, account);
}

/** What an MCP connection may do, one OAuth scope each, in the order people read them. */
/** The groups a connected app holds, in consent's order; `admin` only where its client asked for it by name. */
export const CAPABILITY_GROUPS = ['read', 'build', 'deploy', 'spend', 'delete', 'admin'] as const;
export type CapabilityGroup = (typeof CAPABILITY_GROUPS)[number];

/** An MCP client a person allowed on the consent page (an OAuth grant, a principal of its own). */
export interface ConnectedAppView {
    object: 'connected_app';
    id: string;
    client: { name: string; uri: string | null; id: string };
    capabilities: string[];
    spend_cap_usd_per_month: number | null;
    /** Purchases under this go through without asking; null always asks. */
    auto_approve_under_usd: number | null;
    spent_usd_this_month: number;
    /** Pinned to one of the account's users; null acts for the account. */
    user_id: string | null;
    profile: string;
    resource: string;
    created_at: string;
    last_used_at: string | null;
    revoked_at: string | null;
    /** Once revoked, its owner may turn it back on as it was (`restoreConnectedApp`): a connection NoClick itself makes
     *  (its assistant's). A client a person connected connects again instead. */
    restorable: boolean;
}

export async function listConnectedApps(client: NoClick, options: { cursor?: string | null } = {}): Promise<Page<ConnectedAppView>> {
    const page = await client.request<{ data: ConnectedAppView[]; next_cursor: string | null }>('GET', '/v1/connected_apps', {
        ...account,
        query: { cursor: options.cursor },
    });
    return { data: page.data, nextCursor: page.next_cursor ?? null };
}

/** Returns the revoked view (`revoked_at` set). */
export function revokeConnectedApp(client: NoClick, appId: string): Promise<ConnectedAppView> {
    return client.request<ConnectedAppView>('DELETE', `/v1/connected_apps/${encodeURIComponent(appId)}`, account);
}

/** Turns a revoked connection NoClick makes back on, as it was; returns it live (`revoked_at` null). */
export function restoreConnectedApp(client: NoClick, appId: string): Promise<ConnectedAppView> {
    return client.request<ConnectedAppView>('POST', `/v1/connected_apps/${encodeURIComponent(appId)}/restore`, account);
}

export function resolveObject(client: NoClick, ref: string, signal?: AbortSignal): Promise<ObjectRef> {
    return client.request<ObjectRef>('GET', `/v1/objects/${encodeURIComponent(ref)}`, { ...account, signal });
}

/** `GET /v1/cards/program` on the wire (`Card.program()` reads it camelCased). */
export interface CardProgramView {
    object: 'card_program';
    status: CardProgramStatus;
    requirements_due: string[];
    company_name: string | null;
    country: string;
    currency: string;
    onboarding_url: string;
}

/** A session for Stripe's embedded account-onboarding form. */
export interface CardOnboardingSession {
    object: 'card_onboarding_session';
    client_secret: string;
    publishable_key: string;
    account: string;
    expires_at: string | null;
    program: CardProgramView;
}

/**
 * Opens the company's card program on first use (a key gets 403). 409 `conflict` once the issuer
 * rejected the company, `not_available` where cards aren't enabled.
 */
export function createCardOnboardingSession(client: NoClick): Promise<CardOnboardingSession> {
    return client.request<CardOnboardingSession>('POST', '/v1/cards/program/session', account);
}


/** Where the account's request for machines stands (`GET /v1/machines/vetting`). */
export type MachineAccessStatus = 'not_submitted' | 'pending' | 'approved' | 'rejected';

export interface MachineAccessView {
    object: 'machine_vetting';
    status: MachineAccessStatus;
    /** The machines usage policy's version the request accepted (the current one before any request). */
    policy_version: string;
    company_name?: string;
    website?: string;
    country?: string;
    /** What the account said its machines will run. */
    use_case?: string;
    submitted_at?: string;
    decided_at?: string | null;
    /** Why NoClick declined it. */
    reason?: string | null;
}

export interface MachineAccessRequest {
    company_name: string;
    website: string;
    /** ISO 3166-1 alpha-2, upper case. */
    country: string;
    use_case: string;
    accept_usage_policy: boolean;
}

export function getMachineAccess(client: NoClick, signal?: AbortSignal): Promise<MachineAccessView> {
    return client.request<MachineAccessView>('GET', '/v1/machines/vetting', { ...account, signal });
}

/** Asks NoClick for machines; only the signed-in owner may (a key gets 403), and an approved account gets 409. */
export function requestMachineAccess(client: NoClick, input: MachineAccessRequest): Promise<MachineAccessView> {
    return client.request<MachineAccessView>('POST', '/v1/machines/vetting', { ...account, json: input });
}
