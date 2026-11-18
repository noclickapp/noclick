// Fixtures for bringing your own numbers:
// your account's phone provider connection and the numbers in it, main-line (kept there and
// connected through it), support-line (ported in), and port requests in each state. c.ts's phone
// routes serve these numbers beside the bought one, b.ts lists the ports to a read of their kind,
// and a.ts lists the connections. Connecting, disconnecting, porting, retrying and canceling keep
// session state; tests call `resetNumberFixtures()` between cases.
import { AGENTS, DAY, FIXTURE_NOW_MS, HOUR, USERS, ago, apiError, fixtureId, list, ok, type FixtureReply, type FixtureRequest, type FixtureRoute, type FixtureSet } from '../core';

const ACME = USERS[0].id;
const NOW = new Date(FIXTURE_NOW_MS).toISOString();
const later = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();

/** Ids from 130,000: numbers under kind digit 7, ports under the operations' digit 4; connections 13x under 6. */
const numberId = (n: number) => fixtureId(7, 130_000 + n);
const portId = (n: number) => fixtureId(4, 130_000 + n);

/** What a ported number costs a month in these fixtures. */
const MONTHLY_USD = 1;

/**
 * The phone provider connections (integration `twilio`): your account's holds its own SID and auth
 * token, which can connect a number; Acme's holds an API key, which can't verify the provider's
 * signed calls, so connecting through it is refused.
 */
export const PHONE_PROVIDER_CONNECTIONS = [
    {
        object: 'connection' as const,
        id: fixtureId(6, 130),
        name: 'phone',
        integration: 'twilio',
        credential_type: 'twilio_account',
        user_id: null,
        status: 'connected' as const,
        account: 'Harbor Dental',
        verification: { reachable: true, samples: [{ label: '+12125550123', value: null }], message: 'The provider answered with your numbers.' },
        connect_link: null,
        connected_at: ago(12 * DAY),
        created_at: ago(12 * DAY),
        updated_at: ago(12 * DAY),
    },
    {
        object: 'connection' as const,
        id: fixtureId(6, 131),
        name: 'phone',
        integration: 'twilio',
        credential_type: 'twilio_api_key',
        user_id: ACME,
        status: 'connected' as const,
        account: null,
        verification: null,
        connect_link: null,
        connected_at: ago(3 * DAY),
        created_at: ago(3 * DAY),
        updated_at: ago(3 * DAY),
    },
];

/** The numbers in the account's provider account: main-line is connected already (`connectable` says so); one still rings an old IVR. */
const PROVIDER_NUMBERS = [
    { number: '+12125550123', label: 'Main line', routed_elsewhere: false },
    { number: '+12125550188', label: 'Sales', routed_elsewhere: true },
    { number: '+16465550110', label: '(646) 555-0110', routed_elsewhere: false },
];

export interface NumberRow {
    object: 'phone_number';
    id: string;
    name: string | null;
    number: string;
    source: 'connected' | 'ported';
    /** The provider connection a connected number runs through. */
    connection: string | null;
    user_id: string | null;
    agent_id: string | null;
    transfer_to: string | null;
    texts: boolean;
    callers: string;
    record_calls: boolean;
    monthly_usd: number | null;
    created_at: string;
}

function numberRow(fields: Pick<NumberRow, 'id' | 'name' | 'number' | 'source' | 'connection' | 'user_id' | 'agent_id' | 'monthly_usd' | 'created_at'>): NumberRow {
    return { object: 'phone_number', transfer_to: null, texts: false, callers: 'anyone', record_calls: false, ...fields };
}

const MAIN_LINE = numberRow({
    id: numberId(1),
    name: 'main-line',
    number: '+12125550123',
    source: 'connected',
    connection: 'phone',
    user_id: null,
    agent_id: AGENTS[1].id,
    monthly_usd: null,
    created_at: ago(9 * DAY),
});

const SUPPORT_LINE = numberRow({
    id: numberId(2),
    name: 'support-line',
    number: '+13125550175',
    source: 'ported',
    connection: null,
    user_id: null,
    agent_id: AGENTS[0].id,
    monthly_usd: MONTHLY_USD,
    created_at: ago(30 * DAY),
});

export const BROUGHT_NUMBERS: readonly NumberRow[] = [MAIN_LINE, SUPPORT_LINE];

type Json = Record<string, unknown>;

/** Each number's own state on the letter, from the port's. */
function numberStatus(status: unknown, step: unknown): string {
    if (status === 'succeeded') return 'ported';
    if (status === 'failed') return 'rejected';
    if (status === 'running') return step === 'scheduled' ? 'scheduled' : 'submitted';
    return 'draft';
}

/** A port of `numbers` on one letter: `number` is the first, `numbers` each with its state and date. */
function port(n: number, numbers: readonly string[], fields: Json & { status: string }, age: number): Json {
    const created = ago(age);
    const status = numberStatus(fields.status, fields.step);
    return {
        object: 'operation',
        id: portId(n),
        kind: 'phone.port_in',
        step: null,
        summary: numbers.join(', '),
        sign_url: null,
        port_at: null,
        monthly_usd: MONTHLY_USD,
        user_id: null,
        result: null,
        error: null,
        created_at: created,
        updated_at: created,
        events: [],
        ...fields,
        number: numbers[0],
        numbers: numbers.map((number) => ({ number, status, port_at: fields.port_at ?? null })),
    };
}

const signUrl = (id: string) => `https://noclick.com/sign/port/${id}`;

/** One port in each state, newest first; the scheduled one moves two numbers on different days. */
export const PORT_REQUESTS: readonly Json[] = [
    port(1, ['+14155550190'], { status: 'awaiting_human', sign_url: signUrl(portId(1)), user_id: ACME }, 3 * HOUR),
    port(2, ['+16175550142'], { status: 'running', step: 'submitted' }, 5 * HOUR),
    port(3, ['+15125550133'], {
        status: 'failed',
        error: { type: 'invalid_request', message: "The current carrier says the account number doesn't match its records for this number.", field: 'account_number' },
    }, DAY),
    {
        ...port(4, ['+17185550160', '+17185550161'], { status: 'running', step: 'scheduled', port_at: later(3 * DAY) }, 2 * DAY),
        numbers: [
            { number: '+17185550160', status: 'scheduled', port_at: later(2 * DAY) },
            { number: '+17185550161', status: 'scheduled', port_at: later(3 * DAY) },
        ],
    },
    port(5, [SUPPORT_LINE.number], { status: 'succeeded', result: { phone_numbers: [SUPPORT_LINE] } }, 32 * DAY),
];

// ── session state ──────────────────────────────────────────────────────────

interface State {
    numbers: Map<string, NumberRow>;
    ports: Map<string, Json>;
    /** Rows made this session and the fixture set they were made in. */
    made: Map<string, FixtureSet>;
    seq: number;
}

let state: State = fresh();

function fresh(): State {
    return {
        numbers: new Map(BROUGHT_NUMBERS.map((n) => [n.id, structuredClone(n)])),
        ports: new Map(PORT_REQUESTS.map((p) => [String(p.id), structuredClone(p)])),
        made: new Map(),
        seq: 0,
    };
}

/** Forget what a session connected, ported and changed. */
export function resetNumberFixtures(): void {
    state = fresh();
}

function visible(set: FixtureSet, id: string): boolean {
    const madeIn = state.made.get(id);
    return madeIn ? madeIn === set : set === 'populated';
}

/** The numbers brought from elsewhere a read in `set` sees, for c.ts's phone routes. */
export function broughtNumbers(set: FixtureSet): NumberRow[] {
    return [...state.numbers.values()].filter((n) => visible(set, n.id));
}

/** The ports a read in `set` sees, newest first, for b.ts's operation reads. */
export function portRequests(set: FixtureSet): Json[] {
    return [...state.ports.values()].filter((p) => visible(set, String(p.id))).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
}

export function findPortRequest(id: string): Json | undefined {
    return state.ports.get(id);
}

/** Cancel a port before it's scheduled; null for an id that isn't a port. */
export function cancelPortRequest(id: string): FixtureReply | null {
    const p = state.ports.get(id);
    if (!p) return null;
    if (p.step === 'scheduled') return apiError(409, 'conflict', `The carrier has scheduled ${p.number} to move, so the port can't be canceled now.`, undefined, { operation_status: p.status });
    if (!['awaiting_human', 'running', 'queued'].includes(String(p.status))) {
        return apiError(409, 'conflict', `The port already ${p.status}.`, 'Nothing to cancel; read its result with GET /v1/operations/{id}.', { operation_status: p.status });
    }
    Object.assign(p, { status: 'canceled', step: null, sign_url: null, updated_at: NOW, error: { type: 'canceled', message: 'The port was canceled.' } });
    return ok(p);
}

function nextN(): number {
    state.seq += 1;
    return state.seq;
}

// ── connecting ─────────────────────────────────────────────────────────────

/** The provider connection a write names (its name or id), in the scope the call acts for. */
function providerConnection(r: FixtureRequest, ref: string): (typeof PHONE_PROVIDER_CONNECTIONS)[number] | FixtureReply {
    const user = r.headers.get('NoClick-User');
    const c = PHONE_PROVIDER_CONNECTIONS.find((row) => row.user_id === user && (row.name === ref || row.id === ref));
    if (!c) return apiError(404, 'not_found', `No phone provider connection '${ref}' ${user ? `for ${user}` : 'on your account'}.`, 'Connect the provider account first, with its account SID and auth token.', { field: 'connection' });
    if (c.credential_type !== 'twilio_account') {
        return apiError(
            400,
            'invalid_request',
            `'${c.name}' holds an API key, which can't connect a number: NoClick checks the provider's signed calls with the account's own secret.`,
            "Connect the provider account with its account SID and auth token instead.",
            { field: 'connection' }
        );
    }
    return c;
}

const isReply = (value: unknown): value is FixtureReply => typeof value === 'object' && value !== null && !('object' in value);

function connectable(r: FixtureRequest): FixtureReply {
    const c = providerConnection(r, r.query.get('connection') ?? '');
    if (isReply(c)) return c;
    return list(
        PROVIDER_NUMBERS.map((n) => {
            const connected = [...state.numbers.values()].find((row) => row.number === n.number);
            return { object: 'connectable_number', ...n, phone_number_id: connected?.id ?? null, agent_id: connected?.agent_id ?? null };
        })
    );
}

function connect(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as { number?: string; connection?: string; name?: string };
    const c = providerConnection(r, body.connection ?? '');
    if (isReply(c)) return c;
    if (!PROVIDER_NUMBERS.some((n) => n.number === body.number)) {
        return apiError(404, 'not_found', `${body.number} isn't in the provider account behind '${c.name}'.`, 'Pick one from PhoneNumber.connectable(connection).', { field: 'number' });
    }
    const existing = [...state.numbers.values()].find((n) => n.number === body.number);
    if (existing) {
        return apiError(409, 'conflict', `${body.number} is already connected to NoClick as ${existing.name ?? existing.number}: a number rings one agent.`, 'Disconnect it there first.', {
            existing_id: existing.id,
        });
    }
    const n = nextN();
    const row = numberRow({
        id: numberId(100 + n),
        name: body.name ?? null,
        number: String(body.number),
        source: 'connected',
        connection: c.name,
        user_id: r.headers.get('NoClick-User'),
        agent_id: null,
        monthly_usd: null,
        created_at: NOW,
    });
    state.numbers.set(row.id, row);
    state.made.set(row.id, r.set);
    return ok(row);
}

function disconnect(r: FixtureRequest): FixtureReply {
    const row = state.numbers.get(r.params.id);
    if (!row || !visible(r.set, row.id)) return apiError(409, 'conflict', 'Only a connected number is disconnected; a bought or ported one is released.', 'Release it instead.');
    if (row.source !== 'connected') return apiError(409, 'conflict', `${row.number} is a NoClick number now, so it's released, not disconnected.`, 'Release it instead.');
    state.numbers.delete(row.id);
    return ok({ ...row, deleted: true });
}

// ── porting ────────────────────────────────────────────────────────────────

interface PortBody {
    numbers?: string[];
    max_monthly_usd?: number;
    name?: string;
    account_holder?: string;
    account_name?: string;
    service_address?: Record<string, string | undefined>;
    account_number?: string;
    billing_number?: string;
    pin?: string;
}

/** What the letter says: a correction to one asks the account holder to sign again. */
const LETTER_FACTS = ['account_holder', 'account_name', 'service_address', 'account_number', 'billing_number'] as const;

/** Refused as the API's request validation refuses a body: the field, then what's wrong with it. */
function invalidField(field: string, message: string): FixtureReply {
    return apiError(400, 'invalid_request', `${field}: ${message}`, 'Fix the fields listed in errors and retry.', { field });
}

/** A service address the way the API validates one; null when it's whole. */
function addressError(address: PortBody['service_address']): FixtureReply | null {
    if (!address) return invalidField('service_address', 'Field required');
    for (const key of ['street', 'city', 'region', 'postal_code'] as const) {
        if (!address[key]) return invalidField(`service_address.${key}`, 'Field required');
    }
    if (!/^[A-Z]{2}$/.test(String(address.region))) return invalidField('service_address.region', "String should match pattern '^[A-Z]{2}$'");
    if (!/^\d{5}$/.test(String(address.postal_code))) return invalidField('service_address.postal_code', "String should match pattern '^\\d{5}$'");
    return null;
}

function startPort(r: FixtureRequest, numbers: readonly string[], signs: boolean, userId: string | null): FixtureReply {
    const n = nextN();
    const id = portId(100 + n);
    const row = port(n + 100, numbers, { status: signs ? 'awaiting_human' : 'running', step: signs ? null : 'submitted', sign_url: signs ? signUrl(id) : null, user_id: userId }, 0);
    state.ports.set(id, row);
    state.made.set(id, r.set);
    return { status: 202, body: row };
}

function portIn(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as PortBody;
    // In the order the API's model checks them.
    for (const field of ['account_holder', 'account_name'] as const) {
        if (!body[field]) return invalidField(field, 'Field required');
    }
    const address = addressError(body.service_address);
    if (address) return address;
    if (!body.account_number) return invalidField('account_number', 'Field required');
    if (!body.numbers?.length) return invalidField('numbers', 'Field required');
    if (body.max_monthly_usd === undefined) return invalidField('max_monthly_usd', 'Field required');
    const numbers = [...new Set(body.numbers)];
    const local = numbers.find((number) => !/^\+1\d{10}$/.test(number));
    if (local !== undefined) {
        return apiError(400, 'invalid_request', `'${local}' is not a US local number.`, 'Port local numbers in international format (+1…).', { field: 'numbers' });
    }
    if (body.name !== undefined && numbers.length > 1) {
        return apiError(400, 'invalid_request', "A name is one number's: port several without one and name them after.", undefined, { field: 'name' });
    }
    const connected = [...state.numbers.values()].find((row) => row.source === 'connected' && numbers.includes(row.number));
    if (connected) {
        return apiError(
            400,
            'invalid_request',
            `${connected.number} is connected through your phone provider: disconnect it first, then port it in.`,
            `POST /v1/phone_numbers/${connected.id}/disconnect puts its calls back where they went while it moves.`,
            { field: 'numbers', existing_id: connected.id }
        );
    }
    if (body.max_monthly_usd < MONTHLY_USD) {
        return apiError(402, 'price_exceeded', `Each number would cost $${MONTHLY_USD.toFixed(2)} a month, more than max_monthly_usd.`, `Raise max_monthly_usd to at least ${MONTHLY_USD}.`, { price_usd: MONTHLY_USD });
    }
    return startPort(r, numbers, true, r.headers.get('NoClick-User'));
}

/** A rejected port sent again: a corrected letter fact, or a refusal of the name it was signed with, means signing again. */
function retry(r: FixtureRequest): FixtureReply {
    const p = state.ports.get(r.params.id);
    if (!p) return apiError(404, 'not_found', `No port with id ${r.params.id}.`);
    if (p.status !== 'failed') return apiError(409, 'conflict', 'Only a rejected port is sent again.', undefined, { operation_status: p.status });
    const body = (r.body ?? {}) as PortBody;
    if (body.service_address) {
        const address = addressError(body.service_address);
        if (address) return address;
    }
    const rejectedFor = (p.error as { field?: string } | null)?.field;
    const signs = LETTER_FACTS.some((fact) => body[fact] !== undefined) || rejectedFor === 'account_holder' || rejectedFor === 'account_name';
    const numbers = (p.numbers as { number: string }[]).map((n) => n.number);
    return startPort(r, numbers, signs, (p.user_id as string | null) ?? null);
}

export const routes: readonly FixtureRoute[] = [
    { method: 'POST', path: '/v1/phone_numbers/connect', reply: connect },
    { method: 'POST', path: '/v1/phone_numbers/:id/disconnect', reply: disconnect },
    { method: 'POST', path: '/v1/phone_numbers/port_in', reply: portIn },
    { method: 'POST', path: '/v1/phone_numbers/port_in/:id/retry', reply: retry },
];

/** c.ts places this before its `/v1/phone_numbers/:id`. */
export const connectableRoute: FixtureRoute = { method: 'GET', path: '/v1/phone_numbers/connectable', reply: connectable };
