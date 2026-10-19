// The usage page's data, as `usage:page` and `usage:charges` send it (backend/wss/handlers/usage_page_handler.py).
// Money is dollars throughout: `total_cost` is dollars in the table, at what each thing cost (an older plan's rows at
// its prices). The page reads the payer's charges grouped every way it breaks them down (UsageGroup) and lists the
// charges a page at a time (ChargeRow). `billing` is the money behind it where the deployment bills; null elsewhere.

/** billing/schema.py */
export type UsageType = 'ai_usage' | 'ai_builder' | 'ai_testing' | 'cpu_usage' | 'gpu_usage' | 'api_usage' | 'recurring';

/** billing/schema.py */
export type UnitType =
    | 'tokens'
    | 'cpu_hours'
    | 'gpu_hours'
    | 'requests'
    | 'mb'
    | 'gb_hours'
    | 'seconds'
    | 'images'
    | 'rows'
    | 'million_requests'
    | 'hour'
    | 'month';

/** user_usage_events.metadata: the keys the page reads (repositories/usage_page.py CHARGE_METADATA_KEYS). */
export interface UsageEventMetadata {
    /** The member who ran the work when the workspace's owner pays for it. */
    actual_user_id?: string;
    /** The automation, agent node and run the charge was recorded in. Charges recorded before runs were stamped
     *  carry the automation alone. */
    workflow_id?: string;
    node_id?: string;
    execution_id?: string;
    /** 'coordinator': the account's chat with NoClick. */
    surface?: string;
    coordinator_job_id?: string;
    /** Developer-platform attribution. */
    platform_api?: { key_id?: string; tenant_id?: string; agent_id?: string; project_id?: string; surface?: string };
    project_id?: string;
    database_id?: string;
    repo_id?: string;
    inbox_id?: string;
    /** A text's number. */
    phone_number_id?: string;
    /** A call's number on your side, and which way it went. */
    number?: string;
    direction?: 'inbound' | 'outbound';
    /** voice/call: 'number' on a bought number, else the line it came in on. */
    channel?: string;
    /** The address an email went from; a metered reading's start, beside `to`, its end. */
    from?: string;
    to?: string;
    operation?: string;
    model?: string;
    prompt_tokens?: number;
    completion_tokens?: number;
    credential_id?: string;
    domain?: string;
    years?: number;
    call_sid?: string;
    minutes?: number;
    /** A site's traffic in a reading, counted (the ledger's quantity is in millions). */
    requests?: number;
    /** A reversal mirrors the charge it gives back. */
    reverses?: string;
    reason?: string;
}

/** What a group and a charge share, so every breakdown reads either. */
export interface UsageRow {
    id: string;
    /** A charge's time; a group's first charge's time. */
    created_at: string;
    /** The payer: a workspace's work is billed to its owner. */
    user_id: string;
    usage_type: UsageType;
    /** A model id, or a service path like 'agent/sandbox', 'apps/hosting', 'voice/call'. */
    usage_subtype: string;
    quantity: number;
    unit_type: UnitType;
    /** Dollars charged. */
    total_cost: number;
    /** Where the deployment bills: the vendor's cost (a group sums it, a charge's own is null when not known). */
    cost_usd?: number | null;
    /** Where the deployment bills: the old monthly top-up's share and the balance's share. The plan's included share
     *  is total_cost − topup_paid − balance_paid. */
    topup_paid?: number;
    balance_paid?: number;
    /** The user's own key or resource: nobody is charged for it. */
    user_resource: boolean;
    metadata: UsageEventMetadata;
    /** The group key: a charge carries its group's. */
    k: string;
}

/** The payer's charges in one window and UTC day that agree on every breakdown field. */
export interface UsageGroup extends UsageRow {
    /** How many charges it holds. */
    n: number;
    /** In this period (true) or the one before. */
    current: boolean;
    day: string;
    prompt_tokens: number;
    completion_tokens: number;
}

/** One charge. */
export interface ChargeRow extends UsageRow {
    organization_id: string | null;
}

/** A charge's run, for "Open run" (the shape the dashboard's run dialog opens). */
export interface ChargeRun {
    id: string;
    workflow: { id: string; name: string };
    status: string;
    startedAt: string;
    durationMs: number | null;
    trigger: string;
    nodesExecuted: number;
    error?: string;
}

export interface ChargesPage {
    rows: ChargeRow[];
    runs: Record<string, ChargeRun>;
    /** Pass back for the next page; null at the end. */
    next: string | null;
}

/** What narrows the charges: the groups a drill, a service or a search picked (null: all) and one UTC day. */
export interface ChargesQuery {
    keys: string[] | null;
    day: string | null;
}

/** Where the page reads charges from: the backend, or a fixture. */
export type ChargesSource = (query: ChargesQuery, cursor: string | null, limit: number) => Promise<ChargesPage>;

/** A charge on a date rather than with use: a number's month (`period_amount` every 30 days from `paid_through`),
 *  a connection's hours (`hourly_amount`). */
export interface RecurringChargeRow {
    id: string;
    credential_id: string;
    charge_type: string;
    hourly_amount: number | null;
    period_amount: number | null;
    paid_through: string | null;
    created_at: string;
    label: string;
}

/** A domain, renewing as a charge on its expiry. */
export interface DomainRow {
    id: string;
    name: string;
    renewal_usd: number;
    renewal_years: number;
    expires_at: string;
    auto_renew: boolean;
}

/** The pools a payer draws from, as the deployment's credit gate reads them. */
export interface PlanState {
    /** 'free_member' on the plans that charge what things cost; 'legacy' on the older plans. */
    billing_model: 'free_member' | 'legacy';
    tier: string;
    window_start: string;
    window_end: string;
    previous_start: string;
    /** Usage the plan pays for in the window, and what the gate counts as used of it; null when unlimited. */
    included_usd: number | null;
    included_used_usd: number;
    /** Free's daily allowance and today's use of it. */
    daily_usd: number | null;
    daily_used_usd: number | null;
    /** The plan's fee on funds added; null on the older plans. */
    fee_rate: number | null;
    /** Older plans: the monthly top-up's pool and what's used of it. */
    topup_usd: number;
    topup_used_usd: number;
    /** The plan's own renewal on the card. */
    plan_price_usd: number;
    renews_at: string | null;
    renews_yearly?: boolean;
}

/** Auto top-up as the page reads it. */
export interface AutoTopUpState {
    enabled: boolean;
    thresholdUsd: number;
    amountUsd: number;
    monthlyCapUsd: number;
    pausedReason: string | null;
    methodLabel: string | null;
    hasMethod: boolean;
    currency: string | null;
    /** This UTC month's automatic top-ups so far. */
    monthUsd: number;
}

/** The money behind the page, where the deployment bills. */
export interface UsageBilling {
    plan: PlanState;
    /** What was added less what it paid for; below zero is owed. `has` once funds were ever added. */
    balance: { usd: number; has: boolean };
    funds: { usd: number; fee: number; count: number };
    /** What friends who joined through the account's link added this period, each by the friend's first name (null
     *  without one); money in that no one paid, so never counted as funds added. */
    referrals?: { usd: number; friend: string | null; at: string }[];
    autoTopUp: AutoTopUpState | null;
    recurring: RecurringChargeRow[];
    domains: DomainRow[];
}

/** Names for the ids the charges carry. */
export interface Directory {
    workflows: Record<string, { name: string }>;
    /** `${workflow_id}:${node_id}`, or a platform agent's id; `chat`: the agent that is the account's chat with NoClick. */
    agents: Record<string, { name: string; chat?: boolean }>;
    people: Record<string, { name: string }>;
    projects?: Record<string, { name: string }>;
    databases?: Record<string, { name: string }>;
    numbers?: Record<string, { name: string }>;
    inboxes?: Record<string, { name: string }>;
    keys?: Record<string, { name: string }>;
}

/** `usage:page`'s answer, as the backend sends it (groups and charges flat, before `toSnapshot`). */
export interface UsagePageData {
    now: string;
    account: { id: string };
    period: { window_start: string; window_end: string; previous_start: string };
    billing: UsageBilling | null;
    groups: (Omit<UsageGroup, 'metadata' | 'id'> & Record<string, unknown>)[];
    directory: Directory;
    charges: ChargesPage;
}

/** Everything the page derives from. */
export interface UsageSnapshot {
    now: string;
    account: { id: string };
    period: { window_start: string; window_end: string; previous_start: string };
    billing: UsageBilling | null;
    groups: UsageGroup[];
    directory: Directory;
}
