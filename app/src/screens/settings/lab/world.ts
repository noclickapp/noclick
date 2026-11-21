// The Settings lab's world: every read Settings' own sections make on the platform API (the email alerts, the account,
// its monthly spending cap, its workstreams), answered as the API answers the account's signed-in owner or one of its
// keys (`actsAs`), and Usage's reads as the Usage lab's member (../../usage/lab/world.ts). A scene picks the alerts'
// switches, the plan, the balance, the cap and what its period spent, and the workstreams; the rest is the same for
// every scene. A host's own lab answers the
// same reads with `settingsAnswers`.
import type { NoClick } from 'noclick';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { CLOCK as USAGE_CLOCK, ledgerFetch, worldApi, type ActsAs, type LedgerCall, type Observe } from '@/screens/usage/lab/world';
import { NOTIFICATION_CATEGORIES } from '../notifications';

export type { ActsAs, Observe };

/** The lab's moment: the Usage lab's, so the Usage section reads as it does there. */
export const CLOCK = USAGE_CLOCK;

export interface SettingsApiWorld {
    /** The email alerts: some of them off (as they are unless the read never answers). */
    prefs?: 'some-off' | 'waiting';
    tier: 'free' | 'member';
    /** The balance as the account reads it. */
    balanceUsd: number;
    /** The account's monthly spending cap in whole dollars; null where none is set. */
    capUsd: number | null;
    /** What the cap's period has spent. */
    spentUsd: number;
    /** The account's workstreams: a few open and one archived (as they are unless said), none yet, or a read that never
     *  answers. */
    workstreams?: 'some' | 'none' | 'waiting';
}

/** The workstreams a world starts with, as GET /v1/workstreams lists them (`merged_into` is the lab's own: the one a
 *  merged workstream joined). */
interface LabWorkstream {
    id: string;
    name: string;
    spent_usd: number;
    events: number;
    archived: boolean;
    merged_into?: string;
}

const WORKSTREAMS: readonly LabWorkstream[] = [
    { id: 'ws_support', name: 'Customer support', spent_usd: 12.4, events: 318, archived: false },
    { id: 'ws_launch', name: 'Spring launch', spent_usd: 8.1, events: 142, archived: false },
    { id: 'ws_menu', name: 'Menu refresh', spent_usd: 0, events: 0, archived: false },
    { id: 'ws_q3', name: 'Q3 launch', spent_usd: 0, events: 0, archived: true },
];

export const ACCOUNT_ID = 'u_ada';
export const OWNER_EMAIL = 'ada@example.test';
/** The account's billing period. */
export const PERIOD = { period_start: '2026-10-01T00:00:00Z', resets_at: '2026-11-01T00:00:00Z' };
const PREFS = { run_failure: true, credits: true, digest: false, approvals: true, referrals: false };

const KEY_REFUSES_RAISE =
    'One of the account’s keys lowers its monthly spending cap, or sets one where there’s none: raising or removing it is the owner’s.';
const KEY_REFUSES_ACCOUNT = 'A key reads the account and can’t change it.';

/** Settings' own reads on the platform API in `world`, each answered as the API answers `actsAs`; null for a call that
 *  isn't one of them. A change lasts as long as the client it answers. */
export function settingsAnswers(world: SettingsApiWorld, actsAs: ActsAs = 'owner'): (call: LedgerCall) => Promise<Response> | null {
    let prefs: Record<string, boolean> = { ...Object.fromEntries(NOTIFICATION_CATEGORIES.map((c) => [c.key, true])), ...PREFS };
    let cap = world.capUsd;
    let workstreams: LabWorkstream[] = world.workstreams === 'none' ? [] : WORKSTREAMS.map((w) => ({ ...w }));
    const workstreamView = ({ merged_into: _, ...w }: LabWorkstream) => ({ object: 'workstream', ...w, created_at: '2026-10-02T09:00:00Z', updated_at: '2026-10-02T09:00:00Z' });
    const capView = () => ({
        object: 'spend_cap',
        cap_usd: cap,
        ...(cap === null ? {} : { spent_usd: world.spentUsd, ...PERIOD, reached: world.spentUsd >= cap }),
        set_by: null,
    });
    // The account, as the API reads it to its owner, or (without its owner's fields) to a key.
    const account = () => ({
        object: 'account',
        id: ACCOUNT_ID,
        plan: { tier: world.tier },
        balance: { remaining_usd: world.balanceUsd, funds_usd: Math.max(world.balanceUsd, 0), resets_at: PERIOD.resets_at },
        month: { ...PERIOD, spent_usd: world.spentUsd },
        ...(actsAs === 'owner' ? { email: OWNER_EMAIL, spend_cap: capView() } : {}),
    });
    const answer = (body: unknown) => Promise.resolve(Response.json(body));
    const refused = (message: string) => Promise.resolve(Response.json({ error: { type: 'permission_denied', message } }, { status: 403 }));
    return ({ method, url, body }) => {
        const route = `${method} ${url.pathname}`;
        if (route === 'GET /v1/notifications') {
            return world.prefs === 'waiting' ? new Promise<Response>(() => undefined) : answer({ object: 'notifications', categories: prefs });
        }
        if (route === 'PATCH /v1/notifications') {
            prefs = { ...prefs, ...(body?.categories as Record<string, boolean>) };
            return answer({ object: 'notifications', categories: prefs });
        }
        if (route === 'GET /v1/account') return answer(account());
        if (route === 'PATCH /v1/account') {
            if (actsAs === 'key') return refused(KEY_REFUSES_ACCOUNT);
            if (body && 'spend_cap_usd' in body) cap = body.spend_cap_usd as number | null;
            return answer(account());
        }
        if (route === 'GET /v1/usage/limits') return answer({ object: 'usage_limits', ...PERIOD, keys: [], users: [], agents: [], projects: [], account: capView() });
        if (route === 'GET /v1/workstreams') {
            if (world.workstreams === 'waiting') return new Promise<Response>(() => undefined);
            const archived = url.searchParams.get('archived') === 'true';
            const listed = workstreams.filter((w) => !w.merged_into && w.archived === archived).sort((a, b) => b.spent_usd - a.spent_usd);
            return answer({ object: 'list', data: listed.map(workstreamView), period_start: PERIOD.period_start, period_end: PERIOD.resets_at, unnamed_usd: 1.25 });
        }
        if (method === 'PATCH' && url.pathname.startsWith('/v1/workstreams/')) {
            // Renamed onto another's name it merges there, which is open again; then archived or brought back.
            const ref = decodeURIComponent(url.pathname.slice('/v1/workstreams/'.length)).toLowerCase();
            const current = workstreams.find((w) => !w.merged_into && (w.id === ref || w.name.toLowerCase() === ref));
            if (!current) return Promise.resolve(Response.json({ error: { type: 'not_found', message: `No workstream '${ref}'.` } }, { status: 404 }));
            let now = current;
            let mergedFrom: { id: string; name: string } | null = null;
            const name = typeof body?.name === 'string' ? body.name.split(/\s+/).filter(Boolean).join(' ') : null;
            if (name) {
                const target = workstreams.find((w) => !w.merged_into && w.id !== current.id && w.name.toLowerCase() === name.toLowerCase());
                if (target) {
                    workstreams = workstreams.map((w) => (w.id === current.id ? { ...w, merged_into: target.id } : w.id === target.id ? { ...w, archived: false, spent_usd: w.spent_usd + current.spent_usd, events: w.events + current.events } : w));
                    mergedFrom = { id: current.id, name: current.name };
                    now = workstreams.find((w) => w.id === target.id)!;
                } else {
                    workstreams = workstreams.map((w) => (w.id === current.id ? { ...w, name } : w));
                    now = workstreams.find((w) => w.id === current.id)!;
                }
            }
            if (typeof body?.archived === 'boolean') {
                const archived = body.archived;
                workstreams = workstreams.map((w) => (w.id === now.id ? { ...w, archived } : w));
                now = workstreams.find((w) => w.id === now.id)!;
            }
            return answer({ ...workstreamView({ ...now, spent_usd: 0, events: 0 }), ...(mergedFrom ? { merged_from: mergedFrom } : {}) });
        }
        if (route === 'PUT /v1/usage/limits/account') {
            const next = (body?.cap_usd ?? null) as number | null;
            if (actsAs === 'key') {
                if (cap !== null && (next === null || next > cap)) return refused(KEY_REFUSES_RAISE);
                // Removing a cap where there's none changes nothing.
                if (next !== null) cap = next;
                return answer(capView());
            }
            cap = next;
            return answer(capView());
        }
        return null;
    };
}

/** A client over `world` in place of the page's: Settings' own reads answered here, Usage's as the Usage lab's member
 *  (the change stream refused, as where the API doesn't serve it); `observe` hears every call. No retries, so a refused
 *  change fails at once. */
export function settingsClient(world: SettingsApiWorld, observe?: Observe, actsAs: ActsAs = 'owner'): NoClick {
    const own = settingsAnswers(world, actsAs);
    const usage = ledgerFetch(worldApi({ billed: 'member' }, actsAs));
    const answering = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const call: LedgerCall = {
            method: (init?.method ?? 'GET').toUpperCase(),
            url: new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url),
            body: typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null,
        };
        const answered = own(call) ?? usage(input, init);
        observe?.(call, answered);
        return answered;
    }) as typeof fetch;
    return workFixtureClient(answering, { maxRetries: 0 });
}
