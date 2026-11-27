// Fixtures for Cards (a design, shown only in the lab) and Browser profiles:
// canned /v1 answers shaped like the designed routes, filtered the way those
// routes would filter, so the lab and the page tests run the real client.
import { AGENTS, DAY, FIXTURE_NOW_MS, HOUR, MIN, PAGE_ERROR, USERS, ago, apiError, fixtureId, list, ok, pageList, rememberOperation, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';
import { userMatches } from './c';

const ACME = USERS[0].id;
const USER_42 = USERS[1].id;
const CONCIERGE = AGENTS[1].id;
const ASSISTANT_ANA = AGENTS.find((a) => a.name === 'assistant' && a.user_id === USER_42)!.id;
const NOW = new Date(FIXTURE_NOW_MS).toISOString();
const later = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();

/** Ids under kind digit 7 at 80xxx: cards 800xx, transactions 801xx, profiles 802xx, browsers 803xx. */
const rid = (group: number, n: number) => fixtureId(7, 80_000 + group + n);

function found<T>(r: FixtureRequest, row: T | undefined, what: string): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    return row ? ok(row) : apiError(404, 'not_found', `No such ${what}.`);
}

function listed<T extends { user_id: string | null }>(r: FixtureRequest, rows: readonly T[]): FixtureReply {
    return pageList(r, rows.filter((row) => userMatches(r.query, row.user_id)));
}

// ── cards ──────────────────────────────────────────────────────────────────

export const CARDS = [
    {
        object: 'card',
        id: rid(0, 1),
        name: 'Office supplies',
        last4: '4242',
        brand: 'visa',
        exp_month: 9,
        exp_year: 2029,
        status: 'active',
        limit_usd: 1500,
        interval: 'month',
        spent_usd: 412.3,
        resets_at: '2026-10-01T00:00:00Z',
        merchants: ['office_supplies'],
        require_approval_above_usd: 200,
        agent_id: CONCIERGE,
        user_id: ACME,
        created_at: ago(24 * DAY),
    },
    {
        object: 'card',
        id: rid(0, 2),
        name: 'Travel',
        last4: '8210',
        brand: 'visa',
        exp_month: 3,
        exp_year: 2030,
        status: 'frozen',
        limit_usd: 3000,
        interval: 'month',
        spent_usd: 1180,
        resets_at: '2026-10-01T00:00:00Z',
        merchants: ['travel'],
        require_approval_above_usd: 500,
        agent_id: ASSISTANT_ANA,
        user_id: USER_42,
        created_at: ago(8 * DAY),
    },
    {
        object: 'card',
        id: rid(0, 3),
        name: 'Software',
        last4: '0005',
        brand: 'mastercard',
        exp_month: 11,
        exp_year: 2028,
        status: 'active',
        limit_usd: 200,
        interval: 'transaction',
        spent_usd: 186,
        resets_at: null,
        merchants: ['software'],
        require_approval_above_usd: null,
        // A fresh number for every checkout.
        single_use: true,
        agent_id: null,
        user_id: null,
        created_at: ago(60 * DAY),
    },
];

/** The held Herman Miller charge's approval: an owner-answerable `human.approve` operation. */
export const CARD_APPROVAL_OPERATION = {
    object: 'operation',
    id: fixtureId(4, 80_401),
    kind: 'human.approve',
    status: 'awaiting_human',
    summary: 'Approve $640.00 at Herman Miller on Office supplies (•••• 4242)?',
    user_id: ACME,
    key_id: null,
    agent_id: CONCIERGE,
    result: null,
    error: null,
    created_at: ago(12 * MIN),
    updated_at: ago(12 * MIN),
    events: [],
};

interface ChargeFields {
    amount_usd: number;
    merchant: string;
    merchant_category: string;
    status: 'approved' | 'declined' | 'pending_approval';
    decline_reason?: string;
    approval_id?: string;
    at: string;
}

const charge = (n: number, cardId: string, fields: ChargeFields) => ({
    object: 'card_transaction',
    id: rid(100, n),
    card_id: cardId,
    decline_reason: null as string | null,
    approval_id: null as string | null,
    ...fields,
});

export const CARD_TRANSACTIONS = [
    charge(1, CARDS[0].id, { amount_usd: 640, merchant: 'Herman Miller', merchant_category: 'office_supplies', status: 'pending_approval', approval_id: CARD_APPROVAL_OPERATION.id, at: ago(12 * MIN) }),
    charge(2, CARDS[0].id, { amount_usd: 86.4, merchant: 'Staples', merchant_category: 'office_supplies', status: 'approved', at: ago(2 * HOUR) }),
    charge(3, CARDS[0].id, { amount_usd: 142.18, merchant: 'Amazon Business', merchant_category: 'office_supplies', status: 'approved', at: ago(1 * DAY) }),
    charge(4, CARDS[0].id, { amount_usd: 249.99, merchant: 'Best Buy', merchant_category: 'electronics', status: 'declined', decline_reason: 'merchant_not_allowed', at: ago(2 * DAY) }),
    charge(5, CARDS[0].id, { amount_usd: 183.72, merchant: 'Staples', merchant_category: 'office_supplies', status: 'approved', at: ago(5 * DAY) }),
    charge(6, CARDS[1].id, { amount_usd: 329, merchant: 'Hilton', merchant_category: 'travel', status: 'declined', decline_reason: 'frozen', at: ago(3 * HOUR) }),
    charge(7, CARDS[1].id, { amount_usd: 768, merchant: 'Marriott', merchant_category: 'travel', status: 'declined', decline_reason: 'not_approved', at: ago(2 * DAY) }),
    charge(8, CARDS[1].id, { amount_usd: 412, merchant: 'Delta Air Lines', merchant_category: 'travel', status: 'approved', at: ago(6 * DAY) }),
    charge(9, CARDS[2].id, { amount_usd: 260, merchant: 'Datadog', merchant_category: 'software', status: 'declined', decline_reason: 'over_limit', at: ago(4 * HOUR) }),
    charge(10, CARDS[2].id, { amount_usd: 120, merchant: 'Notion', merchant_category: 'software', status: 'approved', at: ago(3 * DAY) }),
    charge(11, CARDS[2].id, { amount_usd: 45, merchant: 'Figma', merchant_category: 'software', status: 'approved', at: ago(9 * DAY) }),
    charge(12, CARDS[2].id, { amount_usd: 21, merchant: 'GitHub', merchant_category: 'software', status: 'approved', at: ago(20 * DAY) }),
];

const FUNDING = {
    object: 'card_funding', balance_usd: 2480, pending_usd: 640, available_usd: 1840,
    top_up_url: 'https://noclick.com/dashboard/developers/resources/cards/funding',
    bank_transfer: { bank_name: 'Test Bank', routing_number: '110000000', account_number: '9800012345671', networks: ['ach', 'wire'] },
    frozen_since: null as string | null,
};

/** Card issuing: active in the populated set, not applied for in the others. */
export function cardProgram(status: 'not_started' | 'pending_verification' | 'active' | 'rejected' | 'restricted') {
    return {
        object: 'card_program',
        status,
        requirements_due: status === 'pending_verification' || status === 'restricted' ? ['company.tax_id', 'representative.verification.document'] : [],
        company_name: status === 'not_started' ? null : 'Acme Developer Inc',
        country: 'US',
        currency: 'usd',
        onboarding_url: 'https://noclick.com/dashboard/developers/resources/cards/onboarding',
    };
}

const programFor = (r: FixtureRequest) => cardProgram(r.set === 'populated' ? 'active' : 'not_started');

/** The balance went below zero: NoClick froze every card until it's funded (tests pass these as `routes`). */
export const FROZEN_FUNDING = { ...FUNDING, balance_usd: -42.5, pending_usd: 0, available_usd: -42.5, frozen_since: '2026-09-25T12:00:00Z' };
const frozenByBalance = (card: (typeof CARDS)[number]) => ({ ...card, status: 'frozen', status_reason: 'negative_balance' });
export const CARDS_FROZEN_ROUTES: FixtureRoute[] = [
    { method: 'GET', path: '/v1/cards', reply: (r) => listed(r, CARDS.map(frozenByBalance)) },
    { method: 'GET', path: '/v1/cards/funding', reply: () => ok(FROZEN_FUNDING) },
    { method: 'GET', path: '/v1/cards/program', reply: () => ok(cardProgram('active')) },
    { method: 'GET', path: '/v1/cards/:id', reply: (r) => found(r, CARDS.map(frozenByBalance).find((c) => c.id === r.params.id), 'card') },
];

function withCard(id: string, change: (card: (typeof CARDS)[number]) => Record<string, unknown>) {
    const card = CARDS.find((c) => c.id === id);
    return card ? { ...card, ...change(card) } : undefined;
}

const cardRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/cards',
        reply: (r) => {
            const status = r.query.get('status');
            const agent = r.query.get('agent_id');
            return listed(r, CARDS.filter((c) => (status ? c.status === status : c.status !== 'closed') && (!agent || c.agent_id === agent)));
        },
    },
    // Before `/v1/cards/:id`, which would match them.
    {
        method: 'GET',
        path: '/v1/cards/funding',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            if (r.set === 'populated') return ok(FUNDING);
            const program = programFor(r);
            return apiError(409, 'not_available', "Card issuing isn't active for your account yet.", `Finish card onboarding in the console: ${program.onboarding_url}`, {
                program_status: program.status,
                requirements_due: program.requirements_due,
            });
        },
    },
    { method: 'GET', path: '/v1/cards/program', reply: (r) => (r.set === 'error' ? PAGE_ERROR : ok(programFor(r))) },
    {
        method: 'POST',
        path: '/v1/cards/program/session',
        reply: (r) =>
            r.set === 'error'
                ? PAGE_ERROR
                : ok({
                      object: 'card_onboarding_session',
                      client_secret: 'accs_secret_lab_fixture',
                      publishable_key: 'pk_test_lab_fixture',
                      account: 'acct_1LabFixture',
                      expires_at: later(30 * MIN),
                      program: programFor(r),
                  }),
    },
    { method: 'GET', path: '/v1/cards/:id', reply: (r) => found(r, CARDS.find((c) => c.id === r.params.id), 'card') },
    {
        method: 'GET',
        path: '/v1/cards/:id/transactions',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const status = r.query.get('status');
            const rows = CARD_TRANSACTIONS.filter((t) => t.card_id === r.params.id && (!status || t.status === status));
            return list(rows.slice(0, Number(r.query.get('limit') ?? 20)));
        },
    },
    {
        method: 'POST',
        path: '/v1/cards',
        reply: (r) => {
            const body = (r.body ?? {}) as Record<string, unknown>;
            if (typeof body.limit_usd !== 'number' || body.limit_usd <= 0) return apiError(400, 'invalid_request', 'limit_usd must be more than 0.', undefined, { field: 'limit_usd' });
            const userId = r.headers.get('NoClick-User');
            if (CARDS.some((c) => c.name === body.name && c.user_id === userId && c.status !== 'closed')) {
                return apiError(409, 'conflict', `An open card is already named '${String(body.name)}'.`, 'Pick another name, or use Card.from_name.');
            }
            return ok({
                ...CARDS[0],
                id: rid(0, 9),
                last4: '1881',
                spent_usd: 0,
                merchants: null,
                require_approval_above_usd: null,
                agent_id: null,
                ...body,
                user_id: userId,
                resets_at: body.interval === 'month' ? '2026-10-01T00:00:00Z' : body.interval === 'day' ? later(8 * HOUR) : null,
                created_at: NOW,
            });
        },
    },
    { method: 'PATCH', path: '/v1/cards/:id', reply: (r) => found(r, withCard(r.params.id, () => (r.body ?? {}) as Record<string, unknown>), 'card') },
    { method: 'POST', path: '/v1/cards/:id/freeze', reply: (r) => found(r, withCard(r.params.id, () => ({ status: 'frozen' })), 'card') },
    { method: 'POST', path: '/v1/cards/:id/unfreeze', reply: (r) => found(r, withCard(r.params.id, () => ({ status: 'active' })), 'card') },
    { method: 'POST', path: '/v1/cards/:id/close', reply: (r) => found(r, withCard(r.params.id, () => ({ status: 'closed' })), 'card') },
    {
        method: 'POST',
        path: '/v1/cards/:id/reveal',
        reply: (r) => {
            const card = CARDS.find((c) => c.id === r.params.id);
            if (!card) return apiError(404, 'not_found', 'No such card.');
            return ok({
                object: 'card_details',
                card_id: card.id,
                url: `https://noclick.com/c/${rid(500, 1)}`,
                expires_at: new Date(FIXTURE_NOW_MS + 10 * MIN).toISOString(),
                last4: card.last4,
                brand: card.brand,
                exp_month: card.exp_month,
                exp_year: card.exp_year,
                single_use: card.single_use ?? false,
                amount_usd: null,
                closes_at: null,
                cardholder: 'Acme Developer Inc',
                billing_address: { line1: '548 Market St', city: 'San Francisco', state: 'CA', postal_code: '94104', country: 'US' },
            });
        },
    },
];

// ── browser profiles ───────────────────────────────────────────────────────

export const BROWSER_PROFILES = [
    {
        object: 'browser_profile',
        id: rid(200, 1),
        name: 'ana-work',
        user_id: USER_42,
        sites: [{ domain: 'portal.example.com', signed_in_at: ago(6 * DAY), signed_in_by: 'ana@example.com', last_used_at: ago(2 * HOUR) }],
        last_used_at: ago(2 * HOUR),
        created_at: ago(6 * DAY + HOUR),
    },
    {
        object: 'browser_profile',
        id: rid(200, 2),
        name: 'acme-ops',
        user_id: ACME,
        sites: [
            { domain: 'vendor.example.com', signed_in_at: ago(18 * DAY), signed_in_by: 'ops@acme.test', last_used_at: ago(1 * DAY) },
            { domain: 'carrier.example.com', signed_in_at: ago(30 * DAY), last_used_at: null },
        ],
        last_used_at: ago(1 * DAY),
        created_at: ago(31 * DAY),
    },
];

export const BROWSERS = [
    {
        object: 'browser',
        id: rid(300, 1),
        status: 'running',
        profile_id: BROWSER_PROFILES[0].id,
        agent_id: ASSISTANT_ANA,
        live_url: `https://noclick.com/live/${rid(300, 1)}`,
        url: 'https://portal.example.com/invoices',
        title: 'Invoices · Portal',
        timeout_s: 900,
        cost_usd: 0.06,
        user_id: USER_42,
        created_at: ago(4 * MIN),
        expires_at: later(11 * MIN),
        closed_at: null,
    },
    {
        object: 'browser',
        id: rid(300, 2),
        status: 'closed',
        profile_id: BROWSER_PROFILES[0].id,
        agent_id: ASSISTANT_ANA,
        live_url: null,
        url: 'https://portal.example.com/invoices/2026-08',
        title: 'August invoices · Portal',
        timeout_s: 900,
        cost_usd: 0.42,
        user_id: USER_42,
        created_at: ago(1 * DAY + 2 * HOUR),
        expires_at: ago(1 * DAY + 2 * HOUR - 15 * MIN),
        closed_at: ago(1 * DAY + 2 * HOUR - 7 * MIN),
    },
    {
        object: 'browser',
        id: rid(300, 3),
        status: 'failed',
        profile_id: BROWSER_PROFILES[1].id,
        agent_id: CONCIERGE,
        live_url: null,
        url: 'https://vendor.example.com/orders',
        title: 'Orders · Vendor',
        timeout_s: 600,
        cost_usd: 0.11,
        user_id: ACME,
        created_at: ago(1 * DAY),
        expires_at: ago(1 * DAY - 10 * MIN),
        closed_at: ago(1 * DAY - 3 * MIN),
    },
];

/** A sign-in the lab starts: `awaiting_human` until the person signs in. */
export const BROWSER_LOGIN_OPERATION = {
    object: 'operation',
    id: fixtureId(4, 80_402),
    kind: 'browser.login',
    status: 'awaiting_human',
    summary: 'Sign in to a site',
    user_id: USER_42,
    key_id: null,
    agent_id: null,
    result: null,
    error: null,
    created_at: NOW,
    updated_at: NOW,
    events: [],
};

/** Operations these pages link to; the Logs fixtures (pages/b.ts) own /v1/operations/:id in the lab. */
export const IDENTITY_OPERATIONS = [CARD_APPROVAL_OPERATION, BROWSER_LOGIN_OPERATION];
IDENTITY_OPERATIONS.forEach(rememberOperation); // "Review approval" and "View operation" open them

const profileRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/browser_profiles',
        reply: (r) => {
            const name = r.query.get('name');
            return listed(r, BROWSER_PROFILES.filter((p) => !name || p.name === name));
        },
    },
    { method: 'GET', path: '/v1/browser_profiles/:id', reply: (r) => found(r, BROWSER_PROFILES.find((p) => p.id === r.params.id), 'browser profile') },
    {
        method: 'POST',
        path: '/v1/browser_profiles/:id/login',
        reply: (r) => {
            const profile = BROWSER_PROFILES.find((p) => p.id === r.params.id);
            if (!profile) return apiError(404, 'not_found', 'No such browser profile.');
            const url = String((r.body as { url?: string } | null)?.url ?? '');
            let domain: string;
            try {
                domain = new URL(url).hostname;
            } catch {
                return apiError(400, 'invalid_request', 'url must be a full https:// address.', undefined, { field: 'url' });
            }
            const human = (r.body as { human?: { email?: string } } | null)?.human;
            const user = USERS.find((u) => u.id === profile.user_id);
            const sent = Boolean(human?.email || user?.email);
            return ok({
                object: 'browser_login',
                url: `https://noclick.com/b/${fixtureId(9, 80_501)}`,
                expires_at: later(DAY),
                domain,
                delivery: { delivered_via: sent ? ['email'] : [], undelivered: [] },
                operation: { ...BROWSER_LOGIN_OPERATION, summary: `Sign in to ${domain}`, user_id: profile.user_id },
            });
        },
    },
    { method: 'DELETE', path: '/v1/browser_profiles/:id/sites/:domain', reply: (r) => ok({ domain: r.params.domain, deleted: true }) },
    { method: 'DELETE', path: '/v1/browser_profiles/:id', reply: (r) => ok({ id: r.params.id, deleted: true }) },
    {
        method: 'GET',
        path: '/v1/browsers',
        reply: (r) => {
            const profile = r.query.get('profile_id');
            const status = r.query.get('status');
            const live = (s: string) => s === 'starting' || s === 'running';
            return listed(
                r,
                BROWSERS.filter((b) => (!profile || b.profile_id === profile) && (!status || (status === 'live' ? live(b.status) : b.status === status)))
                    .slice(0, Number(r.query.get('limit') ?? 50))
            );
        },
    },
];

export const routes: FixtureRoute[] = [...cardRoutes, ...profileRoutes];
