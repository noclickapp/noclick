// Fixtures for Domains:
// the lab story's acmebooking.com (bought, serving the booking app), acme.test
// (connected by Acme, pending DNS for help@mail.acme.test) and globexhq.test (transferred in
// by Globex, its DNS still at its old host). Buying, transferring in, connecting, DNS
// edits, renewal and transfer out keep session state, so a purchase or a transfer moves
// through its steps as the console polls it; tests call `resetDomainFixtures()` between cases.
import {
    DAY,
    FIXTURE_NOW_MS,
    FIXTURE_USER,
    HOUR,
    PAGE_ERROR,
    USERS,
    ago,
    apiError,
    fixtureId,
    list,
    ok,
    type FixtureReply,
    type FixtureRequest,
    type FixtureRoute,
    type FixtureSet,
} from '../core';
import { HELP_INBOX_ID, userMatches } from './c';

/** What a .com costs in these fixtures: its first year, and each year after. */
const COM = { register: 12.99, renew: 21.99 };

const ACME = USERS[0].id;
const later = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();
const NOW = new Date(FIXTURE_NOW_MS).toISOString();

/** Ids under kind digit 7 from 70,000: domains 70,0xx, bought in the lab 70,1xx, what they serve 70,9xx. */
const did = (n: number) => fixtureId(7, 70_000 + n);
/** The app the story's domains serve (the Apps fixtures use this id); the inbox is c.ts's. */
export const BOOKING_APP_ID = did(901);
export { HELP_INBOX_ID };

/** Where connected domains point: the user-sites edge. */
const SITES_TARGET = 'cname.noclick.site';
const BRAND_TARGET = 'pages.noclick.app';

interface RecordRow {
    type: string;
    name: string;
    value: string;
    status: string;
    purpose: string | null;
    required?: boolean;
    managed?: boolean;
}

/** A registrant as the API takes and shows it. */
interface ContactRow {
    name: string;
    email: string;
    phone: string;
    address: string;
    city: string;
    region: string;
    postal_code: string;
    country: string;
    organization?: string;
    agreement_accepted_at?: string;
}

export interface DomainRow {
    object: 'domain';
    id: string;
    name: string;
    source: 'bought' | 'transferred' | 'connected';
    status: string;
    /** NoClick hosts its DNS: a bought domain, or a transferred one after `use_noclick_dns`. */
    noclick_dns: boolean;
    expires_at: string | null;
    auto_renew: boolean | null;
    /** The end of the guaranteed renewal window after `expires_at`; null for a connected domain. */
    renewable_until: string | null;
    renewal_usd: number | null;
    /** The term `renewal_usd` buys: the TLD's minimum. */
    renewal_years: number | null;
    registrant: ContactRow | null;
    records: RecordRow[];
    setup_url: string | null;
    /** Designed: its `*.<name>` records are set too. Absent on rows made before it. */
    wildcard?: boolean;
    /** One entry per name of the domain serving something, `hostname` that name. */
    serves: { kind: 'project' | 'inbox' | 'brand'; id: string; name: string; hostname: string }[];
    registrant_email: string | null;
    registrant_verify_by: string | null;
    transfer_locked_until: string | null;
    user_id: string | null;
    created_at: string;
}

const record = (type: string, name: string, value: string, status: string, purpose: string | null, extra: Partial<RecordRow> = {}): RecordRow => ({
    type,
    name,
    value,
    status,
    purpose,
    ...extra,
});

/** The account's own registrant: acmebooking.com is registered to Dana at Acme Booking. */
const DANA: ContactRow = {
    name: 'Dana Reyes',
    organization: 'Acme Booking',
    email: FIXTURE_USER.email,
    phone: '+14155550188',
    address: '1 Ferry Building',
    city: 'San Francisco',
    region: 'CA',
    postal_code: '94111',
    country: 'US',
    agreement_accepted_at: ago(25 * DAY),
};

function acmebooking(): DomainRow {
    return {
        object: 'domain',
        id: did(1),
        name: 'acmebooking.com',
        source: 'bought',
        status: 'active',
        noclick_dns: true,
        expires_at: later(340 * DAY),
        auto_renew: true,
        renewable_until: later(370 * DAY),
        renewal_usd: COM.renew,
        renewal_years: 1,
        registrant: DANA,
        records: [
            record('ALIAS', '@', SITES_TARGET, 'verified', 'Serves booking at the bare name', { managed: true }),
            record('CNAME', 'www', SITES_TARGET, 'verified', 'Serves booking at www', { managed: true }),
            record('CNAME', 'connect', BRAND_TARGET, 'verified', 'Serves your connect, approval and hand-off pages', { managed: true }),
        ],
        setup_url: null,
        // `brand` serves the pages NoClick shows your users, at connect.acmebooking.com.
        serves: [
            { kind: 'project', id: BOOKING_APP_ID, name: 'booking', hostname: 'acmebooking.com' },
            { kind: 'project', id: BOOKING_APP_ID, name: 'booking', hostname: 'www.acmebooking.com' },
            { kind: 'brand', id: 'brand', name: 'connect.acmebooking.com', hostname: 'connect.acmebooking.com' },
        ],
        registrant_email: FIXTURE_USER.email,
        registrant_verify_by: null,
        transfer_locked_until: later(35 * DAY),
        user_id: null,
        created_at: ago(25 * DAY),
    };
}

function acmeTest(): DomainRow {
    return {
        object: 'domain',
        id: did(2),
        name: 'acme.test',
        source: 'connected',
        status: 'pending_dns',
        noclick_dns: false,
        expires_at: null,
        auto_renew: null,
        renewable_until: null,
        renewal_usd: null,
        renewal_years: null,
        registrant: null,
        // Its own mail stays put: the inbox is on mail.acme.test, which NS records hand to NoClick.
        records: [
            record('TXT', '_noclick', 'noclick-verify=7f3a9c2e1b64', 'verified', 'Proves the domain is yours'),
            record('NS', 'mail', 'ns1.dns.noclick.app', 'pending', 'Hands mail.acme.test to NoClick, for help@mail.acme.test'),
            record('NS', 'mail', 'ns2.dns.noclick.app', 'pending', 'Hands mail.acme.test to NoClick, for help@mail.acme.test'),
        ],
        setup_url: 'https://dns.example-host.test/connect/noclick?domain=acme.test',
        serves: [{ kind: 'inbox', id: HELP_INBOX_ID, name: 'help@mail.acme.test', hostname: 'mail.acme.test' }],
        registrant_email: null,
        registrant_verify_by: null,
        transfer_locked_until: null,
        user_id: ACME,
        created_at: ago(2 * HOUR),
    };
}

/** Moved here from another registrar ten days ago; its DNS still answers at the old host. */
function globexhq(): DomainRow {
    return {
        object: 'domain',
        id: did(3),
        name: 'globexhq.test',
        source: 'transferred',
        status: 'active',
        noclick_dns: false,
        expires_at: later(355 * DAY),
        auto_renew: true,
        renewable_until: later(385 * DAY),
        renewal_usd: COM.renew,
        renewal_years: 1,
        registrant: {
            name: 'Lena Park',
            organization: 'Globex',
            email: USERS[2].email,
            phone: '+13125550147',
            address: '200 W Madison St',
            city: 'Chicago',
            region: 'IL',
            postal_code: '60606',
            country: 'US',
            agreement_accepted_at: ago(10 * DAY),
        },
        records: [],
        setup_url: null,
        serves: [],
        registrant_email: USERS[2].email,
        registrant_verify_by: null,
        transfer_locked_until: later(50 * DAY),
        user_id: USERS[2].id,
        created_at: ago(10 * DAY),
    };
}

/** The records a bought domain's zone holds beyond the managed ones. */
function acmebookingZone(): RecordRow[] {
    return [record('TXT', '@', 'google-site-verification=3pL0x0kA1b2C', 'verified', null)];
}

/** What `use_noclick_dns` finds at a transferred domain's old DNS host, copied for review. */
function copiedRecords(name: string): RecordRow[] {
    const copied = 'Copied from its old DNS host';
    return [
        record('A', '@', '203.0.113.24', 'verified', copied),
        record('CNAME', 'www', name, 'verified', copied),
        record('MX', '@', `10 mail.${name}`, 'verified', copied),
        record('TXT', '@', 'v=spf1 include:_spf.mailhost.example ~all', 'verified', copied),
    ];
}

export const DOMAINS: readonly DomainRow[] = [acmebooking(), acmeTest(), globexhq()];

/** Designed: the registration agreement every registrant accepts (`Domain.agreement()`). */
export const AGREEMENT = { object: 'domain_agreement', url: 'https://noclick.com/legal/domain-registration', version: '2026-10-10' };

// ── session state ──────────────────────────────────────────────────────────

interface Purchase {
    /** The statuses it passes through, one per read by id (the buy answered the first). */
    steps: string[];
    reads: number;
}

interface State {
    domains: Map<string, DomainRow>;
    /** User records in a bought domain's zone, by domain id. */
    zones: Map<string, RecordRow[]>;
    purchases: Map<string, Purchase>;
    /** Domains made this session and the fixture set they were made in. */
    made: Map<string, FixtureSet>;
    seq: number;
}

let state: State = fresh();

function fresh(): State {
    return {
        domains: new Map(DOMAINS.map((d) => [d.id, structuredClone(d)])),
        zones: new Map([
            [did(1), acmebookingZone()],
            [did(3), []],
        ]),
        purchases: new Map(),
        made: new Map(),
        seq: 0,
    };
}

/** Forget what a session bought, connected and changed. */
export function resetDomainFixtures(): void {
    state = fresh();
}

function visible(r: FixtureRequest, d: DomainRow): boolean {
    const madeIn = state.made.get(d.id);
    return madeIn ? madeIn === r.set : r.set === 'populated';
}

/** The domain as a read by id sees it: a purchase or a transfer in progress advances one step per read. */
function advance(id: string): DomainRow | undefined {
    const d = state.domains.get(id);
    const purchase = state.purchases.get(id);
    if (!d || !purchase) return d;
    const status = purchase.steps[Math.min(purchase.reads, purchase.steps.length - 1)];
    purchase.reads += 1;
    d.status = status;
    // The registry's transfer lock starts once a transfer in completes.
    if (d.source === 'transferred' && status === 'active' && !d.transfer_locked_until) d.transfer_locked_until = later(60 * DAY);
    if (status === 'pending_dns' || status === 'registrant_unverified') {
        d.records = [
            record('ALIAS', '@', SITES_TARGET, status === 'pending_dns' ? 'pending' : 'verified', 'Points the bare name at NoClick', { managed: true }),
            record('CNAME', 'www', SITES_TARGET, status === 'pending_dns' ? 'pending' : 'verified', 'Points www at NoClick', { managed: true }),
        ];
    }
    return d;
}

function find(r: FixtureRequest): DomainRow | FixtureReply {
    const d = advance(r.params.id);
    return d && visible(r, d) ? d : apiError(404, 'not_found', 'No such domain.');
}

const isReply = (value: DomainRow | FixtureReply): value is FixtureReply => !('object' in value);

function nextId(): number {
    state.seq += 1;
    return state.seq;
}

// ── search ─────────────────────────────────────────────────────────────────

/** A TLD's terms: `first` buys `minYears`, and each renewal of `minYears` costs `renewal`. */
interface Price {
    first: number;
    renewal: number;
    minYears: number;
    maxYears: number;
    premium?: boolean;
}

const TLD_PRICES: Record<string, Price> = {
    com: { first: COM.register, renewal: COM.renew, minYears: 1, maxYears: 10 },
    app: { first: 14, renewal: 16, minYears: 1, maxYears: 10 },
    dev: { first: 14, renewal: 16, minYears: 1, maxYears: 10 },
    io: { first: 39, renewal: 42, minYears: 1, maxYears: 10 },
    co: { first: 2400, renewal: 30, minYears: 1, maxYears: 5, premium: true },
    ai: { first: 150, renewal: 160, minYears: 2, maxYears: 10 },
};

function priceOf(name: string): Price {
    return TLD_PRICES[name.split('.').pop() ?? ''] ?? { first: 15, renewal: 18, minYears: 1, maxYears: 10 };
}

/** What `years` costs: the minimum term, then renewals of it, prorated. */
function priceFor(price: Price, years: number): number {
    return Math.round((price.first + (price.renewal * (years - price.minYears)) / price.minYears) * 100) / 100;
}

const yearsLabel = (years: number) => (years === 1 ? 'a year' : `${years} years`);

/** The lab's registered marks: a name exactly matching one carries the claims notice while its TLD is in its claims period. */
const TRADEMARKS: Record<string, string> = {
    globex: 'GLOBEX',
};

function claimsNoticeOf(name: string): string | null {
    const mark = TRADEMARKS[name.split('.')[0]];
    if (!mark) return null;
    return [
        '**Trademark Notice**',
        '',
        'You have received this Trademark Notice because you have applied for a domain name which matches at least one trademark record submitted to the Trademark Clearinghouse.',
        '',
        `**Mark:** ${mark}`,
        '**Jurisdiction:** United States',
        '**Goods and services:** Industrial automation software; consulting services.',
        '**Holder:** Globex Corporation',
        '',
        "If you continue with this registration, you represent that you have received and understand this notice and, to the best of your knowledge, your registration and use of the requested domain name will not infringe on the trademark rights listed above.",
    ].join('\n');
}

function offer(name: string, taken: boolean) {
    const price = priceOf(name);
    return {
        object: 'domain_offer',
        name,
        available: !taken,
        price_usd: taken ? null : price.first,
        renewal_usd: taken ? null : price.renewal,
        premium: !taken && !!price.premium,
        min_years: taken ? null : price.minYears,
        max_years: taken ? null : price.maxYears,
        claims_notice: taken ? null : claimsNoticeOf(name),
    };
}

function search(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const q = (r.query.get('q') ?? '').trim().toLowerCase();
    if (!q) return apiError(400, 'invalid_request', 'Search for a word or a name.', undefined, { field: 'q' });
    const [word, ...rest] = q.split('.');
    const tlds = r.query.get('tlds')?.split(',').filter(Boolean) ?? Object.keys(TLD_PRICES);
    const names = [...(rest.length ? [q] : []), ...tlds.map((t) => `${word}.${t}`), `get${word}.com`];
    const owned = new Set([...state.domains.values()].map((d) => d.name));
    const rows = [...new Set(names)].map((name) => offer(name, owned.has(name) || name.endsWith('.app')));
    return list(rows.slice(0, Number(r.query.get('limit') ?? 10)));
}

// ── buying ─────────────────────────────────────────────────────────────────

interface BuyBody {
    name: string;
    max_price_usd: number;
    years?: number;
    auto_renew?: boolean;
    registrant?: ContactRow;
    accept_claims?: boolean;
}

/** Designed: the lab's policy holds purchases above this for a person to approve. */
const APPROVAL_ABOVE_USD = 100;

/** A user's domain needs their details, and every registrant their acceptance of the registration agreement. */
function registrantRefusal(r: FixtureRequest, registrant: ContactRow | undefined, doing: string): FixtureReply | null {
    if (r.headers.get('NoClick-User') && !registrant) {
        return apiError(400, 'invalid_request', `A user's domain is registered to that person, so ${doing} needs their details.`, "Pass registrant with the person's details.", {
            field: 'registrant',
        });
    }
    if (registrant && !registrant.agreement_accepted_at) {
        return apiError(
            400,
            'invalid_request',
            'The registrant must accept the domain registration agreement before a domain is registered to them.',
            'Show them the agreement (GET /v1/domains/agreement) and pass when they accepted it as agreement_accepted_at.',
            { field: 'registrant.agreement_accepted_at' }
        );
    }
    return null;
}

function buy(r: FixtureRequest): FixtureReply {
    const body = r.body as BuyBody;
    const price = priceOf(body.name);
    const years = body.years ?? price.minYears;
    if (years < price.minYears || years > price.maxYears) {
        return apiError(400, 'invalid_request', `.${body.name.split('.').pop()} registers for ${price.minYears} to ${price.maxYears} years, not ${years}.`, `Pass years between ${price.minYears} and ${price.maxYears}.`, {
            field: 'years',
        });
    }
    const refused = registrantRefusal(r, body.registrant, 'buying one');
    if (refused) return refused;
    const claims = claimsNoticeOf(body.name);
    if (claims && !body.accept_claims) {
        return apiError(409, 'action_required', `${body.name} matches a registered trademark: the registrant must see its notice first.`, 'Show the person claims_notice; buy again with accept_claims=true once they still want the name.', {
            field: 'accept_claims',
            claims_notice: claims,
        });
    }
    const total = priceFor(price, years);
    if (body.max_price_usd < total) {
        return apiError(402, 'price_exceeded', `${body.name} costs $${total.toFixed(2)} for ${yearsLabel(years)}, more than max_price_usd.`, `Raise max_price_usd to at least ${total}.`, {
            price_usd: total,
        });
    }
    const userId = r.headers.get('NoClick-User');
    const held = total > APPROVAL_ABOVE_USD;
    const n = nextId();
    const id = did(100 + n);
    state.domains.set(id, {
        object: 'domain',
        id,
        name: body.name,
        source: 'bought',
        status: held ? 'awaiting_human' : 'registering',
        noclick_dns: true,
        expires_at: later(years * 365 * DAY),
        auto_renew: body.auto_renew ?? true,
        renewable_until: later((years * 365 + 30) * DAY),
        renewal_usd: price.renewal,
        renewal_years: price.minYears,
        registrant: body.registrant ?? null,
        records: [],
        setup_url: null,
        serves: [],
        registrant_email: body.registrant?.email ?? FIXTURE_USER.email,
        registrant_verify_by: later(15 * DAY),
        transfer_locked_until: later(60 * DAY),
        user_id: userId,
        created_at: NOW,
    });
    state.zones.set(id, []);
    state.made.set(id, r.set);
    const tail = ['registering', 'pending_dns', 'registrant_unverified'];
    // Held, it waits a few reads for the approver.
    state.purchases.set(id, { steps: held ? ['awaiting_human', 'awaiting_human', 'awaiting_human', ...tail] : tail, reads: 1 });
    return {
        status: 202,
        body: {
            object: 'operation',
            id: fixtureId(4, 7000 + n),
            kind: 'domain.buy',
            status: held ? 'awaiting_human' : 'running',
            summary: body.name,
            domain_id: id,
            price_usd: total,
            user_id: userId,
            result: null,
            error: null,
            created_at: NOW,
            updated_at: NOW,
            events: [],
        },
    };
}

// ── transferring in ────────────────────────────────────────────────────────

function quoteOf(name: string, r: FixtureRequest) {
    const price = priceOf(name);
    // A transfer adds the TLD's minimum term, at the price of buying it.
    const base = { object: 'transfer_quote', name, price_usd: price.first, renewal_usd: price.renewal, years: price.minYears as number | null, locked_until: null as string | null };
    if (name.endsWith('.example')) return { ...base, eligible: false, reason: "NoClick doesn't register .example names, so it can't transfer one in.", price_usd: null, renewal_usd: null, years: null };
    const here = [...state.domains.values()].find((d) => d.name === name && d.source !== 'connected' && visible(r, d));
    if (here) return { ...base, eligible: false, reason: `${name} is already registered through NoClick.` };
    // A `fresh…` name was registered 20 days ago: inside the registry's transfer lock.
    if (name.startsWith('fresh')) {
        const until = later(40 * DAY);
        return { ...base, eligible: false, reason: `${name} was registered 20 days ago, and is inside the registry's transfer lock.`, locked_until: until };
    }
    return { ...base, eligible: true, reason: null };
}

function transferQuote(r: FixtureRequest): FixtureReply {
    const name = (r.query.get('name') ?? '').trim().toLowerCase();
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(name)) return apiError(400, 'invalid_request', `"${name}" isn't a domain name.`, 'Enter a name like acme.com.', { field: 'name' });
    return ok(quoteOf(name, r));
}

interface TransferBody {
    name: string;
    auth_code: string;
    max_price_usd: number;
    registrant?: ContactRow;
}

/** The auth code the lab's registry refuses, a moment after the transfer starts. */
export const WRONG_AUTH_CODE = 'wrong-code';

function transferIn(r: FixtureRequest): FixtureReply {
    const body = r.body as TransferBody;
    const quote = quoteOf(body.name, r);
    if (!quote.eligible) return apiError(409, 'not_available', String(quote.reason), undefined, { locked_until: quote.locked_until });
    const total = quote.price_usd ?? 0;
    if (body.max_price_usd < total) {
        return apiError(402, 'price_exceeded', `Transferring ${body.name} in costs $${total.toFixed(2)}, more than max_price_usd.`, `Raise max_price_usd to at least ${total}.`, { price_usd: total });
    }
    const refused = registrantRefusal(r, body.registrant, 'transferring one in');
    if (refused) return refused;
    const userId = r.headers.get('NoClick-User');
    const held = total > APPROVAL_ABOVE_USD;
    const n = nextId();
    // A connected domain keeps its id and what it serves.
    const connected = [...state.domains.values()].find((d) => d.name === body.name && d.source === 'connected' && visible(r, d));
    const id = connected?.id ?? did(100 + n);
    const price = priceOf(body.name);
    state.domains.set(id, {
        ...(connected ?? {
            object: 'domain',
            id,
            name: body.name,
            records: [],
            setup_url: null,
            serves: [],
            registrant_verify_by: null,
            user_id: userId,
            created_at: NOW,
        }),
        source: 'transferred',
        status: held ? 'awaiting_human' : 'transferring_in',
        noclick_dns: false,
        expires_at: later(price.minYears * 365 * DAY),
        auto_renew: true,
        renewable_until: later((price.minYears * 365 + 30) * DAY),
        renewal_usd: price.renewal,
        renewal_years: price.minYears,
        registrant: body.registrant ?? null,
        registrant_email: body.registrant?.email ?? FIXTURE_USER.email,
        transfer_locked_until: null,
    });
    if (!connected) state.made.set(id, r.set);
    const tail = body.auth_code === WRONG_AUTH_CODE ? ['transferring_in', 'failed'] : ['transferring_in', 'transferring_in', 'active'];
    state.purchases.set(id, { steps: held ? ['awaiting_human', 'awaiting_human', ...tail] : tail, reads: 1 });
    return {
        status: 202,
        body: {
            object: 'operation',
            id: fixtureId(4, 7300 + n),
            kind: 'domain.transfer_in',
            status: held ? 'awaiting_human' : 'running',
            summary: body.name,
            domain_id: id,
            price_usd: total,
            user_id: userId,
            result: null,
            error: null,
            created_at: NOW,
            updated_at: NOW,
            events: [],
        },
    };
}

function useNoclickDns(r: FixtureRequest): FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    if (d.source === 'connected') return apiError(409, 'not_available', `${d.name} is registered elsewhere, so NoClick can't host its DNS.`, 'Transfer it in first.');
    if (d.noclick_dns) return ok({ object: 'domain_dns_move', domain: d, copied: [] });
    const copied = copiedRecords(d.name);
    d.noclick_dns = true;
    state.zones.set(d.id, [...(state.zones.get(d.id) ?? []), ...copied]);
    return ok({ object: 'domain_dns_move', domain: d, copied });
}

// ── connecting ─────────────────────────────────────────────────────────────

function connectRecords(name: string, wildcard = false): RecordRow[] {
    const labels = name.split('.');
    const apex = labels.length === 2;
    const sub = apex ? '' : labels.slice(0, -2).join('.');
    return [
        record('TXT', apex ? '_noclick' : `_noclick.${sub}`, `noclick-verify=${name.length.toString(16)}c41e9a0d27`, 'pending', 'Proves the domain is yours'),
        ...(apex
            ? [
                  record('CNAME', 'www', SITES_TARGET, 'pending', `Serves ${name} at www, its primary address`),
                  record('ALIAS', '@', SITES_TARGET, 'pending', `Serves the bare name; or forward ${name} to www.${name}`, { required: false }),
              ]
            : [record('CNAME', sub, SITES_TARGET, 'pending', `Serves ${name}`)]),
        // Designed: `wildcard` covers every subdomain with one record.
        ...(wildcard ? [record('CNAME', apex ? '*' : `*.${sub}`, SITES_TARGET, 'pending', `Serves every subdomain of ${name}`)] : []),
    ];
}

function connect(r: FixtureRequest): FixtureReply {
    const name = String((r.body as { name?: string })?.name ?? '').trim().toLowerCase();
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(name)) return apiError(400, 'invalid_request', `"${name}" isn't a domain name.`, 'Enter a name like acme.com or book.acme.com.', { field: 'name' });
    const existing = [...state.domains.values()].find((d) => d.name === name && visible(r, d));
    if (existing) return ok(existing);
    if (name.endsWith('.example')) return apiError(409, 'conflict', `Another NoClick account has connected ${name}.`, 'Ask its owner to disconnect it first.');
    const n = nextId();
    const id = did(100 + n);
    const labels = name.split('.');
    const row: DomainRow = {
        object: 'domain',
        id,
        name,
        source: 'connected',
        status: 'pending_dns',
        noclick_dns: false,
        expires_at: null,
        auto_renew: null,
        renewable_until: null,
        renewal_usd: null,
        renewal_years: null,
        registrant: null,
        records: connectRecords(name, (r.body as { wildcard?: boolean })?.wildcard === true),
        wildcard: (r.body as { wildcard?: boolean })?.wildcard === true,
        setup_url: labels.length === 2 ? `https://dns.example-host.test/connect/noclick?domain=${name}` : null,
        serves: [],
        registrant_email: null,
        registrant_verify_by: null,
        transfer_locked_until: null,
        user_id: r.headers.get('NoClick-User'),
        created_at: NOW,
    };
    state.domains.set(id, row);
    state.made.set(id, r.set);
    return ok(row);
}

/** A check finds the next pending record in place; every required one verified makes the domain active. */
function verify(r: FixtureRequest): FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    const pending = d.records.find((rec) => rec.status !== 'verified');
    if (pending) pending.status = 'verified';
    if (d.source === 'connected' && d.records.every((rec) => rec.required === false || rec.status === 'verified')) d.status = 'active';
    return ok(d);
}

// ── managing ───────────────────────────────────────────────────────────────

type Zone = { d: DomainRow; rows: RecordRow[] };

function zone(r: FixtureRequest): Zone | FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    if (!d.noclick_dns) {
        return apiError(409, 'not_available', `${d.name}'s DNS is hosted elsewhere, not by NoClick.`, "Add or change records at the domain's DNS host; domain.records lists the ones it needs.");
    }
    return { d, rows: state.zones.get(d.id) ?? [] };
}

function dnsList(r: FixtureRequest): FixtureReply {
    const z = zone(r);
    if (!('d' in z)) return z;
    return list([...z.d.records, ...z.rows]);
}

function dnsSet(r: FixtureRequest): FixtureReply {
    const z = zone(r);
    if (!('d' in z)) return z;
    const body = r.body as { type: string; name: string; value: string };
    const type = body.type.toUpperCase();
    const name = body.name.trim() || '@';
    if (z.d.records.some((rec) => rec.name === name && (type === 'CNAME' || rec.type === 'CNAME'))) {
        return apiError(409, 'conflict', `${name} is a record NoClick keeps for what ${z.d.name} serves.`, 'Change what the domain serves instead.');
    }
    const rows = z.rows.filter((rec) => !(type === 'CNAME' && rec.type === 'CNAME' && rec.name === name));
    const saved = rows.find((rec) => rec.type === type && rec.name === name && rec.value === body.value) ?? record(type, name, body.value, 'pending', null);
    state.zones.set(z.d.id, rows.includes(saved) ? rows : [...rows, saved]);
    return ok(saved);
}

function dnsDelete(r: FixtureRequest): FixtureReply {
    const z = zone(r);
    if (!('d' in z)) return z;
    const [type, name, value] = ['type', 'name', 'value'].map((k) => r.query.get(k));
    if (z.d.records.some((rec) => rec.type === type && rec.name === name && rec.value === value)) {
        return apiError(409, 'conflict', 'NoClick manages that record for what the domain serves.', 'Change what the domain serves instead.');
    }
    state.zones.set(
        z.d.id,
        z.rows.filter((rec) => !(rec.type === type && rec.name === name && rec.value === value))
    );
    return { status: 204 };
}

function update(r: FixtureRequest): FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    const autoRenew = (r.body as { auto_renew?: boolean }).auto_renew;
    if (d.source === 'connected') return apiError(409, 'not_available', `${d.name} is registered elsewhere, so it renews there.`);
    if (typeof autoRenew === 'boolean') d.auto_renew = autoRenew;
    return ok(d);
}

function renew(r: FixtureRequest): FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    if (d.source === 'connected') return apiError(409, 'not_available', `${d.name} is registered elsewhere, so it renews there.`);
    if (d.renewable_until && Date.parse(d.renewable_until) < FIXTURE_NOW_MS) {
        return apiError(409, 'not_available', `${d.name} is past its renewal window, so it can't be renewed through the API.`, "NoClick support may be able to restore it, at the registry's restore fee.");
    }
    const body = r.body as { years?: number; max_price_usd: number };
    const term = d.renewal_years ?? 1;
    const years = body.years ?? term;
    const total = Math.round(((d.renewal_usd ?? 0) * years * 100) / term) / 100;
    if (body.max_price_usd < total) {
        return apiError(402, 'price_exceeded', `Renewing ${d.name} for ${yearsLabel(years)} costs $${total.toFixed(2)}, more than max_price_usd.`, `Raise max_price_usd to at least ${total}.`, {
            price_usd: total,
        });
    }
    const extend = (at: string | null) => new Date(Date.parse(at ?? NOW) + years * 365 * DAY).toISOString();
    d.expires_at = extend(d.expires_at);
    d.renewable_until = extend(d.renewable_until);
    return {
        status: 202,
        body: { object: 'operation', id: fixtureId(4, 7500 + nextId()), kind: 'domain.renew', status: 'running', summary: d.name, domain_id: d.id, price_usd: total, user_id: d.user_id, result: null, error: null, created_at: NOW, updated_at: NOW, events: [] },
    };
}

function transferOut(r: FixtureRequest): FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    if (d.source === 'connected') return apiError(409, 'not_available', `${d.name} is registered elsewhere; there's nothing to transfer.`);
    if (d.transfer_locked_until && Date.parse(d.transfer_locked_until) > FIXTURE_NOW_MS) {
        const day = new Date(d.transfer_locked_until).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
        return apiError(409, 'not_available', `${d.name} can't be transferred until ${day}: it's inside the registry's transfer lock after it's registered, transferred in or its registrant changes.`, undefined, {
            transfer_locked_until: d.transfer_locked_until,
        });
    }
    d.status = 'transferring_out';
    return ok({ object: 'transfer_code', auth_code: 'Xy7#pQ2!mK9v', unlocked_at: NOW, expires_at: later(5 * DAY) });
}

function disconnect(r: FixtureRequest): FixtureReply {
    const d = find(r);
    if (isReply(d)) return d;
    if (d.source !== 'connected') {
        return apiError(409, 'conflict', `${d.name} is registered through NoClick, so it can't be deleted.`, 'Turn off auto-renew to let it lapse, or transfer it out.');
    }
    const inbox = d.serves.find((s) => s.kind === 'inbox');
    if (inbox) return apiError(409, 'conflict', `${inbox.name} still uses ${d.name}.`, 'Delete the inbox first, then disconnect the domain.');
    state.domains.delete(d.id);
    return { status: 204 };
}

export const routes: readonly FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/domains',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const name = r.query.get('name');
            const rows = [...state.domains.values()].filter((d) => visible(r, d) && userMatches(r.query, d.user_id) && (!name || d.name === name));
            return list(rows);
        },
    },
    { method: 'GET', path: '/v1/domains/search', reply: search },
    { method: 'GET', path: '/v1/domains/transfer_quote', reply: transferQuote },
    { method: 'POST', path: '/v1/domains/transfer_in', reply: transferIn },
    // Designed: the account's default registrant, none set here (tests pass one).
    { method: 'GET', path: '/v1/domains/registrant', reply: () => ok({}) },
    { method: 'GET', path: '/v1/domains/agreement', reply: () => ok(AGREEMENT) },
    { method: 'POST', path: '/v1/domains', reply: buy },
    { method: 'POST', path: '/v1/domains/connect', reply: connect },
    {
        method: 'GET',
        path: '/v1/domains/:id',
        reply: (r) => {
            const d = find(r);
            return isReply(d) ? d : ok(d);
        },
    },
    { method: 'PATCH', path: '/v1/domains/:id', reply: update },
    { method: 'DELETE', path: '/v1/domains/:id', reply: disconnect },
    { method: 'POST', path: '/v1/domains/:id/verify', reply: verify },
    { method: 'GET', path: '/v1/domains/:id/dns', reply: dnsList },
    { method: 'POST', path: '/v1/domains/:id/dns', reply: dnsSet },
    { method: 'DELETE', path: '/v1/domains/:id/dns', reply: dnsDelete },
    { method: 'POST', path: '/v1/domains/:id/renew', reply: renew },
    { method: 'POST', path: '/v1/domains/:id/transfer_out', reply: transferOut },
    { method: 'POST', path: '/v1/domains/:id/use_noclick_dns', reply: useNoclickDns },
];
