// A call NoClick holds for the account owner's yes (a purchase, a deletion), as `GET /v1/approvals/{id}` reads it: what
// it does, what it costs or what goes with it, and how it stands. The owner answers it signed in (`POST
// /v1/approvals/{id}/answer`) or from the link NoClick sends them; a key reads it and links to that page.
import type { DeletionImpact } from '@/screens/resources/platform';
import { formatMoney } from '@/screens/console/lib/format';

export interface ApprovalView {
    object: 'approval';
    id: string;
    /** `canceled`: withdrawn before anyone decided. */
    status: 'pending' | 'approved' | 'declined' | 'expired' | 'used' | 'canceled';
    action: string;
    /** The API mints it from the same words as `action`; shown only where it says something else. */
    summary: string;
    /** What it acts on, in parts, where its area describes it ("the TikTok connection (@morrowbakehouse)" is `{kind:
     *  "connection", app: "TikTok", account: "@morrowbakehouse", name: "tiktok"}`); null otherwise, and on an approval
     *  from before they were kept. */
    subject?: ApprovalSubject | null;
    price: ApprovalPrice | null;
    operation: string;
    /** The held call exactly as NoClick will make it (null on an approval from before they were kept). */
    method?: string | null;
    path?: string | null;
    arguments: Record<string, unknown>;
    /** Why it waits on a person: the account's policy, a limit, terms only a person accepts, what a change charges. */
    reason?: string | null;
    /** `assistant` is the account's own NoClick assistant, which answers in the chat. */
    connection: { kind: 'assistant' | 'agent' | 'connected_app' | 'key'; name: string; grant_id: string | null };
    user_id: string | null;
    created_at: string;
    expires_at: string;
    decided_at: string | null;
    note: string | null;
    /** The apps NoClick sent the account's owner its one-tap link on (`whatsapp`, `imessage`, `email`). */
    sent_to?: string[] | null;
    /** Terms approving accepts, each a required box: read at its `url`, or the `notice` itself. */
    consent?: { terms: string; title: string; text: string; url: string | null; notice: string | null }[];
    /** What a deletion takes along with it; null for anything else. */
    impact?: ApprovalImpact | null;
}

export interface ApprovalSubject {
    kind: string;
    app: string | null;
    account: string | null;
    name: string;
}

export interface ApprovalPrice {
    amount_usd: number;
    recurrence: 'monthly' | 'yearly' | 'once';
    /** The seller's words on what the price covers and when it's charged. */
    terms: string | null;
    /** What a first charge then charges again, every `months` (a domain's renewal, a number's month after its setup);
     *  its amount is null where the seller doesn't know it yet. */
    renewal?: { amount_usd: number | null; months: number } | null;
}

/** A deletion's preview, as the agent saw it before asking. */
export type ApprovalImpact = DeletionImpact;

export const PER: Record<ApprovalPrice['recurrence'], string> = { monthly: 'a month', yearly: 'a year', once: 'once' };

/** How often a renewal comes round: "every month", "every 2 years". */
export function every(months: number): string {
    if (months === 1) return 'every month';
    if (months === 12) return 'every year';
    return months % 12 === 0 ? `every ${months / 12} years` : `every ${months} months`;
}

/** Beside the figure: "a month", "a year", "once", or "now" for a first charge that renews. */
export function priceUnit(price: ApprovalPrice): string {
    return price.renewal ? 'now' : PER[price.recurrence];
}

/** "$1.50 a month", "$40.00 once", "$12.99 now, then $21.99 every year". */
export function priceLabel(price: ApprovalPrice): string {
    const first = `${formatMoney(price.amount_usd)} ${priceUnit(price)}`;
    const { renewal } = price;
    if (!renewal) return first;
    const then = renewal.amount_usd == null ? `${every(renewal.months)} at a price not known yet` : `${formatMoney(renewal.amount_usd)} ${every(renewal.months)}`;
    return `${first}, then ${then}`;
}

/** What an answer sends: the decision, a note, and the terms it accepts. */
export type AnswerBody = { approved: boolean; note: string | null; accepted?: string[] };

export function answerBody(decision: 'approve' | 'decline', note: string, accepted: readonly string[]): AnswerBody {
    return { approved: decision === 'approve', note: note.trim() || null, ...(decision === 'approve' && accepted.length ? { accepted: [...accepted] } : {}) };
}

/** Why a call to the API didn't go: its status, its message and what to do next. */
export interface Failure {
    status: number;
    message: string;
    next_step: string | null;
}
