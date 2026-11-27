// A failed run in words: what Logs says of each cause of failures (`Operation.failures()`) and atop a failed run. The
// API says what failed (its error's type, reason and details) and what it failed on (`failedOn`); this says it as a
// person would, never naming an API route, and takes its fix from the console's one rule (failureFix.ts).
import type { FailedOn, NoClickError, SpendCapExceeded } from 'noclick';
import { capLabel } from '../ui/CapMeter';
import { capOwner, failureFix, type FailureFix, type FixPlace } from './failureFix';

export interface FailureWords {
    /** What happened: with a count, "3 runs stopped at globex’s cap"; without, "Stopped at globex’s cap". */
    what: string;
    /** The rest, in the error's own words where they're plain (a sentence naming an API route is left out). */
    detail: string | null;
    fix: FailureFix | null;
}

const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value.trim() : null);
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const runs = (n: number) => `${n} ${n === 1 ? 'run' : 'runs'}`;

/** The error's own words, less any sentence that names an API route (`PATCH /v1/users/{id}`): those are for code. */
export function plainWords(value: unknown): string | null {
    const words = text(value);
    if (!words) return null;
    const kept = words
        .split(/\.\s+/)
        .map((s) => s.trim())
        .filter((s) => s && !/\/v1\/|\b(GET|POST|PUT|PATCH|DELETE) \/|\.\.\.\//.test(s));
    if (!kept.length) return null;
    const joined = kept.join('. ');
    return /[.!?]$/.test(joined) ? joined : `${joined}.`;
}

function day(value: unknown): string | null {
    const at = text(value);
    const t = at ? Date.parse(at) : NaN;
    return Number.isNaN(t) ? null : new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

interface Said {
    /** What happened to many, after "3 runs" ("stopped at globex’s cap", "were cut off when NoClick restarted"). */
    phrase: string;
    detail: string | null;
}

function capped(error: SpendCapExceeded, place: FixPlace): Said {
    if (error.details.reason === 'unclaimed') return { phrase: 'stopped: the account isn’t claimed yet', detail: plainWords(error.message) };
    if (!error.scope || error.scope === 'account') return { phrase: 'stopped at the account’s monthly cap', detail: plainWords(error.message) };
    const { who, noun } = capOwner(error, place);
    const resets = day(error.details.resets_at);
    // A user's id stays as written: only "the key" and the like start a sentence capitalised.
    const subject = who.startsWith('the ') ? capitalize(who) : who;
    const detail = error.cap == null ? plainWords(error.message) : `${subject} has used its ${capLabel(error.cap)} ${noun} this month${resets ? `; it resets ${resets}` : ''}.`;
    return { phrase: `stopped at ${who}’s ${noun}`, detail };
}

function said(error: NoClickError, place: FixPlace): Said {
    const d = error.details;
    const message = plainWords(error.message);
    const connection = text(d.connection_name) ?? text(d.connection) ?? 'a connection';
    switch (error.type) {
        case 'spend_cap_exceeded':
            return capped(error as SpendCapExceeded, place);
        case 'spending_paused':
            return { phrase: `stopped: ${text(d.user_id) ?? 'the user'}’s spending is paused`, detail: plainWords(d.user_message) };
        case 'payment_required':
            return d.reason === 'provider_out_of_funds'
                ? { phrase: `stopped: ${connection} is out of credits`, detail: message }
                : { phrase: 'stopped: the account is out of funds', detail: message };
        case 'plan_required':
            return { phrase: 'need a paid plan', detail: message };
        case 'credential_disconnected':
            return { phrase: `couldn’t use ${connection}: it’s disconnected`, detail: plainWords(d.provider_said) };
        case 'needs_connection':
            return { phrase: `need ${connection} connected`, detail: message };
        case 'plan_limit_reached':
            return { phrase: `hit ${connection}’s usage limit`, detail: message };
        case 'invalid_request':
            return { phrase: 'were refused for their settings', detail: message };
        case 'permission_denied':
            return { phrase: 'weren’t allowed', detail: message };
        case 'policy_denied':
            return { phrase: 'were declined', detail: message };
        case 'not_found':
            return { phrase: 'found nothing to act on', detail: message };
        case 'conflict':
            return { phrase: 'ran into work already under way', detail: message };
        case 'quota_exceeded':
            return { phrase: 'hit a limit', detail: message };
        case 'rate_limited':
            return { phrase: 'were rate limited', detail: message };
        case 'expired':
            return { phrase: 'ran out of time', detail: message };
        case 'build_failed':
            return { phrase: 'didn’t build', detail: message };
        case 'upstream_error':
            return { phrase: 'couldn’t reach a service', detail: message };
        case 'request_timeout':
            return { phrase: 'took too long', detail: message };
        case 'platform_error':
            // A workflow's step or build is the account's to fix; the rest is NoClick's own.
            switch (d.reason) {
                case 'interrupted':
                    return { phrase: 'were cut off when NoClick restarted', detail: 'It may have partly run: start it again if it still needs doing.' };
                case 'turn_lost':
                    return { phrase: 'were lost before they answered', detail: message };
                case 'run_failed':
                    return { phrase: 'failed at a step', detail: message };
                case 'build_failed':
                    return { phrase: 'didn’t build', detail: message };
                default:
                    return { phrase: 'failed on NoClick’s side', detail: message === 'The operation failed unexpectedly.' ? null : message };
            }
        default:
            return { phrase: 'failed', detail: message };
    }
}

/** One run's form of a phrase written for many ("were refused for their settings" → "was refused for its settings"). */
function forOne(phrase: string): string {
    return phrase.replace(/^were /, 'was ').replace(/^weren’t /, 'wasn’t ').replace(/^need /, 'needs ').replace(' their ', ' its ').replace(' they ', ' it ');
}

/**
 * A failure in words and its fix: `count` how many failed this way (null atop one run), `error` the latest one's,
 * `on` what it failed on.
 */
export function failureWords(error: NoClickError | null, on: FailedOn | null, count: number | null, place: FixPlace): FailureWords {
    const s: Said = error ? said(error, place) : { phrase: 'failed', detail: null };
    const what = count === null ? capitalize(forOne(s.phrase).replace(/^was /, '')) : `${runs(count)} ${count === 1 ? forOne(s.phrase) : s.phrase}`;
    return { what, detail: s.detail, fix: failureFix(error, place, on) };
}

/** Who a cause touched, in a few words: "support-bot for globex", "support-bot and 2 more for 3 users". */
export function touched(
    f: { agentIds: string[]; agentCount: number; userIds: (string | null)[]; userCount: number; keyIds: string[]; keyCount: number },
    place: Pick<FixPlace, 'agentName' | 'keyName'>
): string | null {
    const first = f.agentIds.map((id) => place.agentName?.(id)).find(Boolean) ?? null;
    const agents = f.agentCount === 0 ? null : f.agentCount === 1 ? (first ?? 'an agent') : `${first ?? 'an agent'} and ${f.agentCount - 1} more`;
    const users = f.userCount === 0 ? null : f.userCount === 1 ? (f.userIds[0] ?? 'a user') : `${f.userCount} users`;
    if (agents) return users ? `${agents} for ${users}` : agents;
    if (users) return users;
    const key = f.keyIds.map((id) => place.keyName?.(id)).find(Boolean);
    return f.keyCount === 0 ? null : f.keyCount === 1 ? (key ? `the ${key} key` : 'a key') : `${f.keyCount} keys`;
}
