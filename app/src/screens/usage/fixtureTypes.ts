// The usage dashboard's data contract: the rows billing already keeps, shaped exactly as their tables hold them, so
// the lab's fixtures and a productized loader feed the same renderer. Each field names its source. Everything is
// dollars (`total_cost` is dollars in the table).
import type { AutoTopUpState } from './types';

/** billing/schema.py:36 */
export type UsageType = 'ai_usage' | 'ai_builder' | 'ai_testing' | 'cpu_usage' | 'gpu_usage' | 'api_usage' | 'recurring';

/** billing/schema.py:37-38 */
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

/** user_usage_events.metadata (JSON). Only the keys the dashboard reads. */
export interface UsageEventMetadata {
    /** The member who ran the work when Owner Pays billed it to the owner (cloud/billing/usage_tracker.py:257). */
    actual_user_id?: string;
    /** Who the charge was for, completed as the row is written (cloud/billing/queries.py RESPONSIBLE_METADATA_SQL). */
    responsible_user_id?: string;
    /** The workstream the work belongs to, stamped as running work. */
    workstream_id?: string;
    /** Stamped from CURRENT_WORKFLOW_ID on every row a run records (billing/usage_tracker.py:72-79). */
    workflow_id?: string;
    node_id?: string;
    /** The run the charge belongs to. Only some writers stamp it (an agent's email update, utils/agent_email.py:497);
     *  model calls, sandboxes and calls don't. A row's "Open run" needs it beside CURRENT_WORKFLOW_ID. */
    execution_id?: string;
    /** Work the coordinator started and waited on (coder/coordinator/tasks.py). */
    coordinator_job_id?: string;
    /** Developer-platform attribution: the key, the user, the agent and the app a /v1 call was made for. */
    platform_api?: { key_id: string; tenant_id: string; agent_id?: string; project_id?: string; surface?: string };
    /** An app's rows (apps/*: its hosting meter's readings) and its emails (email/platform_app). Top level, not
     *  under platform_api. */
    project_id?: string;
    /** database/* (platform/databases/meter.py:71). */
    database_id?: string;
    /** storage/repo* rows. */
    repo_id?: string;
    /** email/platform_inbox_* (app_services/mail/outbox.py:160). */
    inbox_id?: string;
    /** phone/text_* (platform/phone/texting.py:689). */
    phone_number_id?: string;
    /** voice/call: 'number' for a call on a bought number, else the NoClick line it came in on
     *  (cloud/voice/internal_routes.py:375). The number itself is not recorded. */
    channel?: string;
    /** email/agent_reply: the address the mail came to, which the reply goes from (nodes/agent/email_reply.py:156). */
    from?: string;
    /** Tool rows (exa, perplexity, x, scraping): which call it was. */
    operation?: string;
    /** Model rows. */
    model?: string;
    prompt_tokens?: number;
    completion_tokens?: number;
    /** Recurring rows (cloud/billing/recurring.py). */
    credential_id?: string;
    charge_id?: string;
    paid_through?: string;
    /** Domain rows (platform/domains/reconcile.py:331). */
    domain?: string;
    years?: number;
    /** Call rows (cloud/voice/internal_routes.py:48). */
    call_sid?: string;
    minutes?: number;
    /** A reversal mirrors the row it gives back (cloud/billing/queries.py:302-310). */
    reverses?: string;
    reason?: string;
    /** What a person reads for the row. Not stored today: the loader would name the row from its workflow, model or
     *  resource (see the lab's PR notes). */
    label?: string;
}

/** One row of user_usage_events (infra/supabase/migrations/20241228225809_init_subscription_tables.sql + later ALTERs). */
export interface UsageEventRow {
    id: string;
    created_at: string;
    /** The PAYER: Owner Pays rewrites workspace work to the workspace owner. */
    user_id: string;
    organization_id: string | null;
    usage_type: UsageType;
    /** A model id, or a service path like 'agent/sandbox', 'apps/hosting', 'voice/call', 'domain/renew', 'phone_number'. */
    usage_subtype: string;
    quantity: number;
    unit_type: UnitType;
    /** Dollars charged. Free/Member: equals cost_usd. Old plans: cost_usd × PLATFORM_MARKUP (3). */
    total_cost: number;
    /** The vendor's cost before anything is added; null when the writer didn't know it. */
    cost_usd: number | null;
    /** 0 on rows priced on Free/Member (a marker: the fee is charged on funds, not usage), null on old-plan rows. */
    fee_usd: number | null;
    /** The old monthly top-up pool's share. */
    topup_paid: number;
    /** The dollar balance's share; it can take the balance below zero. The plan's included share is
     *  total_cost − topup_paid − balance_paid (cloud/billing/queries.py:35-40). */
    balance_paid: number;
    /** The user's own key or resource: it draws on no pool. */
    user_resource: boolean;
    metadata: UsageEventMetadata;
}

/** balance_entries (infra/supabase/migrations/20261008120000_balance_entries.sql). Append-only; the balance is
 *  Σ usd − Σ user_usage_events.balance_paid, never stored (cloud/billing/balance.py:37-50). */
export interface BalanceEntryRow {
    id: string;
    user_id: string;
    kind: 'deposit' | 'refund' | 'refund_failed' | 'dispute' | 'dispute_won' | 'migration' | 'grant' | 'adjustment';
    /** Signed dollars credited. */
    usd: number;
    /** The plan's fee on that payment, paid with it and never credited (20261010120000_at_cost_fee_on_funds.sql). */
    fee_usd: number;
    currency: 'usd' | 'inr';
    /** 'checkout' | 'auto_topup' | 'purchase_link' | … */
    source: string;
    created_at: string;
}

/** balance_recharges (20261008150000_auto_topup.sql:54-71): one auto top-up through its retries. */
export interface BalanceRechargeRow {
    id: string;
    status: 'pending' | 'processing' | 'succeeded' | 'failed' | 'canceled';
    amount_usd: number;
    fee_usd: number;
    attempt: number;
    failure: string | null;
    created_at: string;
    settled_at: string | null;
}

/** recurring_charges (20260316000000…, 20260918100000…), joined to its credential for a name. */
export interface RecurringChargeRow {
    id: string;
    credential_id: string;
    /** MONTHLY_KINDS = {phone_number}; whatsapp_connection bills hourly (cloud/billing/recurring.py:39-47). */
    charge_type: 'phone_number' | 'whatsapp_connection';
    hourly_amount: number | null;
    period_amount: number | null;
    paid_through: string | null;
    over_cap_since: string | null;
    created_at: string;
    /** credentials.name: the number itself, "+1 415 555 0132". */
    label: string;
}

/** platform_domains: a domain renews as a `domain/renew` usage event, not a recurring charge
 *  (platform/domains/reconcile.py:323-336, 869-885). */
export interface DomainRow {
    id: string;
    name: string;
    renewal_usd: number;
    renewal_years: number;
    expires_at: string;
    auto_renew: boolean;
}

/** The pools a payer draws from, as get_credit_usage reports them (cloud/billing/plan_limits.py:442) plus the
 *  window rules of billing/clock.py and plan_limits.py:110-152. */
export interface PlanState {
    /** 'free_member' inside the rollout; 'legacy' on Plus/Pro and credits. */
    billing_model: 'free_member' | 'legacy';
    tier: 'free' | 'member' | 'plus' | 'pro';
    /** The included window: a UTC calendar month on Free, the subscription's month on Member and the old plans. */
    window_start: string;
    window_end: string;
    /** Usage the plan pays for in the window, in dollars (Free 5, Member 10; old plans: base credits ÷ 4). */
    included_usd: number;
    /** Free's daily allowance (UTC day), else null. */
    daily_usd: number | null;
    /** The plan's fee on funds added (Free 0.15, Member 0.05); null on the old plans, which charge none. */
    fee_rate: number | null;
    /** What the plan itself costs each window, charged to the card on file (Stripe), never the balance. */
    plan_price_usd: number;
    /** Old plans only: the monthly top-up add-on's pool, in dollars of old-price usage. */
    topup_usd: number;
}

/** /v1/usage/limits and the workspace budget. UTC calendar month. */
export interface SpendCap {
    scope: 'key' | 'user' | 'agent' | 'project' | 'workspace';
    id: string;
    name: string;
    cap_usd: number;
    spent_usd: number;
}

/** Names for the ids rows carry. */
export interface Directory {
    workflows: Record<string, { name: string }>;
    agents: Record<string, { name: string }>;
    projects: Record<string, { name: string }>;
    people: Record<string, { name: string; you?: boolean }>;
    keys: Record<string, { name: string }>;
    /** platform_databases, by `metadata.database_id`. */
    databases?: Record<string, { name: string }>;
    /** platform phone numbers, by a text's `metadata.phone_number_id`. */
    numbers?: Record<string, { name: string }>;
    /** platform inboxes, by `metadata.inbox_id`. */
    inboxes?: Record<string, { name: string }>;
    /** platform_workstreams, by `metadata.workstream_id`; `reads_as` the one a merged workstream joined. */
    workstreams?: Record<string, { name: string; reads_as?: string }>;
}

/** Everything one usage page reads for one payer. */
export interface UsageSnapshot {
    /** The fixed clock the lab renders at; the product's is billing_now(). */
    now: string;
    account: { id: string; name: string; email: string };
    workspace: { name: string; personal: boolean; members: number };
    /** Who is looking: an owner sees the pool; a member of someone else's workspace sees the owner's pool. */
    viewerIsOwner: boolean;
    plan: PlanState;
    events: UsageEventRow[];
    balanceEntries: BalanceEntryRow[];
    recharges: BalanceRechargeRow[];
    autoTopUp: AutoTopUpState | null;
    recurring: RecurringChargeRow[];
    domains: DomainRow[];
    caps: SpendCap[];
    directory: Directory;
}
