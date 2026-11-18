// The account at a glance, as `GET /v1/status` gives it to the app's key: which account (or which of its users the key
// acts for), its plan, what it has left to spend and what it spent this month. Only the fields the account screen
// shows; the response has more (caps, approvals waiting, what's failing, recent operations).
import type { NoClick } from 'noclick';

export interface AccountStatus {
    /** The account's own name and email; all null when the key acts for one of the account's users. */
    account: { id: string | null; name: string | null; email: string | null };
    /** The user a key acting for one of the account's users acts for. */
    actingFor: { name: string | null; email: string | null } | null;
    /** The account's plan (null for a key acting for a user). */
    plan: { name: string } | null;
    balance: {
        /** What it has left to spend, in dollars; null when it can't be read right now (never a guessed 0). */
        remainingUsd: number | null;
        unlimited: boolean;
    };
    /** What this billing period has cost so far (for a user's key, that user's part). */
    month: { spentUsd: number | null; periodStart: string | null; resetsAt: string | null };
}

type Json = Record<string, unknown>;
const object = (value: unknown): Json => (value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {});
const text = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
const amount = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

export function toAccountStatus(raw: unknown): AccountStatus {
    const body = object(raw);
    const account = object(body.account);
    const actingFor = account.acting_for ? object(account.acting_for) : null;
    const plan = body.plan ? object(body.plan) : null;
    const balance = object(body.balance);
    const month = object(body.month);
    return {
        account: { id: text(account.id), name: text(account.name), email: text(account.email) },
        actingFor: actingFor ? { name: text(actingFor.name), email: text(actingFor.email) } : null,
        plan: plan && text(plan.name) ? { name: text(plan.name)! } : null,
        balance: { remainingUsd: amount(balance.remaining_usd), unlimited: balance.unlimited === true },
        month: { spentUsd: amount(month.spent_usd), periodStart: text(month.period_start), resetsAt: text(month.resets_at) },
    };
}

/** Reads the account through `client`. The SDK has no method for `/v1/status` yet, so this is its request(). */
export async function readAccountStatus(client: NoClick, signal?: AbortSignal): Promise<AccountStatus> {
    return toAccountStatus(await client.request('GET', '/v1/status', { signal }));
}
