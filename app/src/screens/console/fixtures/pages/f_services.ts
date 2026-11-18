// App services in the lab: the booking app sends email from acmebooking.com (and
// broadcasts from news.acmebooking.com), takes test payments behind a claim link and
// signs users in with email and Google; Acme's status-page waits on acme.test's DNS.
import { DAY, HOUR, MIN, PAGE_ERROR, ago, apiError, fixtureId, list, ok, FIXTURE_NOW_MS, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';
import { PROJECTS } from './e_build';

const future = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();

const projectName = (id: string): string | null => PROJECTS.find((p) => p.id === id)?.name ?? null;

export const BOOKING_PROJECT = PROJECTS.find((p) => p.name === 'booking')!;
export const STATUS_PAGE_PROJECT = PROJECTS.find((p) => p.name === 'status-page')!;

const record = (type: string, name: string, value: string, purpose: string, status: 'verified' | 'pending') => ({
    type,
    name,
    value,
    status,
    purpose,
    required: true,
    managed: false,
});

export const BOOKING_EMAIL = {
    object: 'project_email',
    status: 'active',
    from_address: 'bookings@acmebooking.com',
    from_name: 'Acme Booking',
    domain: 'acmebooking.com',
    // Bought through NoClick, so its records were set for it.
    records: [
        { ...record('CNAME', 'nc1._domainkey', 'nc1.dkim.noclick.site', 'DKIM', 'verified'), managed: true },
        { ...record('MX', 'bounce', '10 bounces.mail.noclick.site', 'Bounces', 'verified'), managed: true },
        { ...record('TXT', 'bounce', 'v=spf1 include:mail.noclick.site ~all', 'SPF', 'verified'), managed: true },
        { ...record('TXT', '_dmarc', 'v=DMARC1; p=none;', 'DMARC', 'verified'), required: false },
        { ...record('CNAME', 'nc1._domainkey.news', 'nc1.dkim.noclick.site', 'DKIM for broadcasts', 'verified'), managed: true },
        { ...record('MX', 'bounce.news', '10 bounces.mail.noclick.site', 'Bounces for broadcasts', 'verified'), managed: true },
        { ...record('TXT', 'bounce.news', 'v=spf1 include:mail.noclick.site ~all', 'SPF for broadcasts', 'verified'), managed: true },
    ],
    daily_limit: 1000,
    sent_today: 38,
    paused_reason: null,
    postal_address: 'Acme Booking, 500 Market St, San Francisco, CA 94105',
    broadcast_status: 'active',
    broadcast_from_address: 'bookings@news.acmebooking.com',
    broadcast_daily_limit: 10000,
    broadcast_sent_today: 0,
    broadcast_paused_reason: null,
};

export const STATUS_PAGE_EMAIL = {
    object: 'project_email',
    status: 'pending_dns',
    from_address: 'status@acme.test',
    from_name: 'Acme Status',
    domain: 'acme.test',
    records: [
        record('CNAME', 'nc1._domainkey', 'nc1.dkim.noclick.site', 'DKIM', 'pending'),
        record('MX', 'bounce', '10 bounces.mail.noclick.site', 'Bounces', 'pending'),
        record('TXT', 'bounce', 'v=spf1 include:mail.noclick.site ~all', 'SPF', 'pending'),
        { ...record('TXT', '_dmarc', 'v=DMARC1; p=none;', 'DMARC', 'pending'), status: null, required: false },
    ],
    daily_limit: 200,
    sent_today: 0,
    paused_reason: null,
    postal_address: null,
    broadcast_status: 'pending_dns',
    broadcast_from_address: 'status@news.acme.test',
    broadcast_daily_limit: 1000,
    broadcast_sent_today: 0,
    broadcast_paused_reason: null,
};

const sent = (n: number, to: string, subject: string, status: string, at: string, extra: Record<string, unknown> = {}) => ({
    object: 'sent_email',
    id: fixtureId(7, 90_000 + n),
    to: [to],
    subject,
    status,
    kind: 'message',
    opened: status === 'delivered' ? false : null,
    bounced: status === 'bounced',
    error: null,
    at,
    ...extra,
});

/** Newest first, as the route reads them. */
export const BOOKING_SENDS = [
    sent(9, 'priya@example.com', 'Your Acme Booking sign-in code', 'captured', ago(10 * 1000), {
        kind: 'code',
        environment: 'preview',
        captured: ['priya@example.com'],
        text: 'Your Acme Booking sign-in code is 482913.',
    }),
    sent(8, 'ana@example.com', 'Your booking is confirmed', 'queued', ago(40 * 1000)),
    sent(7, 'ana@example.com', 'Your Acme Booking sign-in code', 'delivered', ago(12 * MIN), { kind: 'code', opened: null }),
    sent(6, 'marcus@example.com', 'Reminder: Friday at 3pm', 'delivered', ago(2 * HOUR), { opened: true }),
    sent(5, 'bob@example.invalid', 'Your booking is confirmed', 'bounced', ago(5 * HOUR), { error: '550 5.1.1 mailbox unavailable' }),
    sent(4, 'li.wei@example.com', 'Receipt for booking #1042', 'delivered', ago(DAY), { opened: true }),
    sent(3, 'sam@example.com', 'Your booking was moved', 'complained', ago(2 * DAY), { error: 'Marked as spam by the recipient.' }),
];

export const BOOKING_PAYMENTS = {
    object: 'project_payments',
    mode: 'test',
    claim_step: 'claim',
    next_step: 'Send the owner claim_url to claim the account before test_expires_at; until then it takes only test cards.',
    claim_url: 'https://api.noclick.com/api/public/payments/claim/cl_8Kq2vXw4',
    test_expires_at: future(6 * DAY + 19 * HOUR),
    dashboard_url: null,
    secrets: ['PAYMENTS_SECRET_KEY', 'PAYMENTS_PUBLISHABLE_KEY', 'PAYMENTS_WEBHOOK_SECRET'],
    processor: 'stripe',
    country: 'US',
    webhook_url: 'https://booking.noclick.site/api/payments/webhook',
};

export const BOOKING_SIGN_IN = {
    object: 'project_sign_in',
    status: 'active',
    providers: ['email', 'google'],
    managed_providers: ['google'],
    users_table: 'users',
    tables: ['users', 'auth_sessions', 'auth_accounts', 'auth_verifications', 'auth_rate_limits'],
    database: 'DB',
    library: 'better-auth',
    version: '1.7.7',
    update_available: null,
    commit: '4e7a1c9d2b8f05e3a6c1d7b9e2f4a8c0d6b3e1f5',
    branch: null,
    edited_files: [],
    callback_urls: {},
    missing_secrets: [],
    secrets: ['AUTH_SECRET', 'AUTH_URL', 'AUTH_PROXY_SECRET', 'NOCLICK_SIGN_IN_CLIENT_ID', 'NOCLICK_SIGN_IN_CLIENT_SECRET'],
    error: null,
};

const OFF = {
    email: {
        object: 'project_email',
        status: 'off',
        from_address: null,
        from_name: null,
        domain: null,
        records: [],
        daily_limit: null,
        sent_today: null,
        paused_reason: null,
        postal_address: null,
        broadcast_status: 'off',
        broadcast_from_address: null,
        broadcast_daily_limit: null,
        broadcast_sent_today: null,
        broadcast_paused_reason: null,
    },
    payments: { object: 'project_payments', mode: 'off', claim_step: null, next_step: null, claim_url: null, test_expires_at: null, dashboard_url: null, secrets: [], processor: 'stripe', country: null, webhook_url: null },
    sign_in: {
        object: 'project_sign_in',
        status: 'off',
        providers: [],
        managed_providers: [],
        users_table: null,
        tables: [],
        database: null,
        library: 'better-auth',
        version: null,
        update_available: null,
        commit: null,
        branch: null,
        edited_files: [],
        callback_urls: {},
        missing_secrets: [],
        secrets: ['AUTH_SECRET', 'AUTH_URL', 'AUTH_PROXY_SECRET'],
        error: null,
    },
};

type Service = keyof typeof OFF;

/** A project's services in this fixture set: the story when populated, everything off otherwise. */
function servicesOf(r: FixtureRequest): Record<Service, unknown> & { sends: readonly unknown[] } {
    const name = r.set === 'populated' ? projectName(r.params.id) : null;
    if (name === 'booking') return { email: BOOKING_EMAIL, payments: BOOKING_PAYMENTS, sign_in: BOOKING_SIGN_IN, sends: BOOKING_SENDS };
    if (name === 'status-page') return { ...OFF, email: STATUS_PAGE_EMAIL, sends: [] };
    return { ...OFF, sends: [] };
}

function read(service: Service) {
    return (r: FixtureRequest): FixtureReply => {
        if (r.set === 'error') return PAGE_ERROR;
        if (!PROJECTS.some((p) => p.id === r.params.id)) return apiError(404, 'not_found', `Project ${r.params.id} not found.`);
        return ok(servicesOf(r)[service]);
    };
}

function enableEmail(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as { domain?: string; from_address?: string; from_name?: string };
    const name = projectName(r.params.id) ?? 'app';
    if (!body.domain) {
        return ok({ ...OFF.email, status: 'active', from_address: `noreply@${name}.noclick.site`, from_name: body.from_name ?? null, daily_limit: 200, sent_today: 0, broadcast_status: 'needs_domain' });
    }
    const from = body.from_address ?? `noreply@${body.domain}`;
    if (body.domain === 'acmebooking.com') return ok({ ...BOOKING_EMAIL, from_address: from, from_name: body.from_name ?? BOOKING_EMAIL.from_name });
    return ok({ ...STATUS_PAGE_EMAIL, domain: body.domain, from_address: from, from_name: body.from_name ?? null });
}

function sendEmail(r: FixtureRequest): FixtureReply {
    const email = servicesOf(r).email as { status: string };
    if (email.status === 'pending_dns') {
        return apiError(409, 'action_required', "The app's email domain isn't verified yet.", 'Add the DNS records from app.email.status() at the domain’s DNS host.');
    }
    if (email.status !== 'active') return apiError(409, 'action_required', 'Email is off for this app.', 'Turn it on with app.email.enable().');
    const body = (r.body ?? {}) as { to?: string[]; subject?: string };
    return ok({ object: 'sent_email', id: fixtureId(7, 90_099), to: body.to ?? [], subject: body.subject ?? null, status: 'queued', opened: null, bounced: false, error: null, at: ago(0) });
}

export const SIGN_IN_OPERATION_ID = fixtureId(4, 9_001);

export const routes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/projects/:id/email', reply: read('email') },
    { method: 'POST', path: '/v1/projects/:id/email', reply: enableEmail },
    { method: 'POST', path: '/v1/projects/:id/email/send', reply: sendEmail },
    {
        method: 'GET',
        path: '/v1/projects/:id/email/messages',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const to = r.query.get('to');
            const rows = servicesOf(r).sends.filter((m) => !to || (m as { to: string[] }).to.includes(to));
            return list(rows.slice(0, Number(r.query.get('limit') ?? 50)));
        },
    },
    { method: 'GET', path: '/v1/projects/:id/payments', reply: read('payments') },
    {
        method: 'POST',
        path: '/v1/projects/:id/payments',
        reply: (r) => {
            const country = (r.body as { country?: string } | null)?.country;
            if (!country) return apiError(400, 'invalid_request', 'country is required to open the test account.', undefined, { field: 'country' });
            return ok({ ...BOOKING_PAYMENTS, country });
        },
    },
    { method: 'GET', path: '/v1/projects/:id/sign_in', reply: read('sign_in') },
    {
        method: 'POST',
        path: '/v1/projects/:id/sign_in',
        reply: (r) =>
            ok({
                object: 'operation',
                id: SIGN_IN_OPERATION_ID,
                kind: 'project.sign_in.enable',
                status: 'running',
                summary: `Add sign-in (${((r.body as { providers?: string[] } | null)?.providers ?? []).join(', ')})`,
                result: null,
                error: null,
                created_at: ago(0),
                updated_at: ago(0),
            }),
    },
];
