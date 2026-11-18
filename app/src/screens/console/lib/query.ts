// The `key:value` query language behind every query bar. `?q=` is the page's
// one source of truth; facets, shortcuts and pills read and write its tokens.
// Each page's schema maps a token onto the SDK option that sends the same list
// parameter, so a console filter and an SDK call always agree.
import { ALL_USERS } from 'noclick';
import { isUuid } from './format';

export type QueryKeyKind = 'list' | 'user' | 'key' | 'agent' | 'time';

export interface QueryKeySpec {
    kind?: QueryKeyKind;
    /** The SDK option this token sets (`status`, `createdAfter`, `userFilter`, …). */
    option: string;
    /** The SDK option a `-key:` token sets; only where the API has a `_not` parameter. */
    negate?: string;
    /** The SDK takes one value, not a list. */
    single?: boolean;
    /** Values offered by autocomplete. */
    values?: readonly string[];
    /** Token value → API value (`answerable:you` → `owner`). */
    map?: Readonly<Record<string, string>>;
}

export type QuerySchema = Readonly<Record<string, QueryKeySpec>>;

export interface QueryToken {
    key: string;
    values: string[];
    negated: boolean;
}

export interface QueryError {
    token: string;
    message: string;
}

export interface ParsedQuery {
    tokens: QueryToken[];
    /** Words that aren't `key:value` tokens. */
    text: string[];
    errors: QueryError[];
}

const TOKEN_RE = /^(-)?([a-z_]+):(.*)$/;

function words(q: string): string[] {
    return q.split(/\s+/).filter(Boolean);
}

export function parseQuery(q: string, schema: QuerySchema): ParsedQuery {
    const tokens: QueryToken[] = [];
    const text: string[] = [];
    const errors: QueryError[] = [];
    for (const word of words(q)) {
        const m = TOKEN_RE.exec(word);
        if (!m) {
            text.push(word);
            continue;
        }
        const [, neg, key, rawValue] = m;
        const spec = schema[key];
        if (!spec) {
            errors.push({ token: word, message: `\`${key}\` isn't a filter here` });
            continue;
        }
        if (neg && !spec.negate) {
            errors.push({ token: word, message: `\`-${key}\` isn't supported` });
            continue;
        }
        const values = rawValue.split(',').map((v) => v.trim()).filter(Boolean);
        if (!values.length) {
            errors.push({ token: word, message: `\`${key}:\` needs a value` });
            continue;
        }
        const at = tokens.findIndex((t) => t.key === key && t.negated === !!neg);
        const token = { key, values, negated: !!neg };
        if (at >= 0) tokens[at] = token;
        else tokens.push(token);
    }
    return { tokens, text, errors };
}

export function formatToken(token: QueryToken): string {
    return `${token.negated ? '-' : ''}${token.key}:${token.values.join(',')}`;
}

/** Each valid `key:value` word in its parsed form (`status:failed,,expired` → `status:failed,expired`); other words as typed. */
export function canonicalQuery(q: string, schema: QuerySchema): string {
    return words(q)
        .map((word) => {
            const parsed = parseQuery(word, schema);
            return parsed.tokens.length === 1 ? formatToken(parsed.tokens[0]) : word;
        })
        .join(' ');
}

export function formatQuery(parsed: Pick<ParsedQuery, 'tokens' | 'text'>): string {
    return [...parsed.tokens.map(formatToken), ...parsed.text].join(' ');
}

export function getToken(parsed: ParsedQuery, key: string, negated = false): string[] | null {
    return parsed.tokens.find((t) => t.key === key && t.negated === negated)?.values ?? null;
}

/** Replace (or with `null`, remove) one token, leaving every other word as typed. */
export function setToken(q: string, key: string, values: readonly string[] | null, negated = false): string {
    const prefix = `${negated ? '-' : ''}${key}:`;
    const kept = words(q).filter((w) => !w.startsWith(prefix));
    if (values && values.length) kept.push(`${prefix}${values.join(',')}`);
    return kept.join(' ');
}

const DURATION_RE = /^(\d+)(m|h|d|w)$/;
const UNIT_MS = { m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000 } as const;

/** `1h` / `1d` / `1w` / `30d` before `now`, or an ISO date; null when neither. */
export function parseTimeValue(value: string, now: number): Date | null {
    const m = DURATION_RE.exec(value);
    if (m) return new Date(now - Number(m[1]) * UNIT_MS[m[2] as keyof typeof UNIT_MS]);
    const t = Date.parse(value);
    return Number.isNaN(t) ? null : new Date(t);
}

export interface AgentHandle {
    id: string;
    name: string;
    userId: string | null;
}

export interface QueryContext {
    now: number;
    /** Loaded agents, to turn `agent:<name>` into an id (names are unique only per user). */
    agents?: readonly AgentHandle[];
    /** The SDK option free text sets (the user list's `q`); otherwise text is an error. */
    textOption?: string;
}

export interface QueryOptions {
    options: Record<string, unknown>;
    errors: QueryError[];
    /** An `agent:` name that several agents share: the page offers a picker. */
    ambiguous: { token: string; candidates: AgentHandle[] }[];
}

/**
 * The SDK options a parsed query sets. A schema with a `user` key reads every
 * user unless the query narrows it (an omitted `user_id` would mean
 * account-level only for the owner).
 */
export function queryToOptions(parsed: ParsedQuery, schema: QuerySchema, ctx: QueryContext): QueryOptions {
    const options: Record<string, unknown> = {};
    const errors = [...parsed.errors];
    const ambiguous: QueryOptions['ambiguous'] = [];
    for (const [, spec] of Object.entries(schema)) {
        if (spec.kind === 'user') options[spec.option] = ALL_USERS;
    }
    for (const token of parsed.tokens) {
        const spec = schema[token.key];
        const raw = formatToken(token);
        const values = token.values.map((v) => spec.map?.[v] ?? v);
        const kind = spec.kind ?? 'list';
        if (kind !== 'list' || spec.single) {
            if (values.length > 1) {
                errors.push({ token: raw, message: `\`${token.key}:\` takes one value` });
                continue;
            }
        }
        const value = values[0];
        if (kind === 'time') {
            const at = parseTimeValue(value, ctx.now);
            if (at) options[spec.option] = at;
            else errors.push({ token: raw, message: `\`${value}\` isn't a time (try 1h, 1d, 1w or a date)` });
        } else if (kind === 'agent') {
            if (isUuid(value)) {
                options[spec.option] = value;
                continue;
            }
            const matches = (ctx.agents ?? []).filter((a) => a.name === value);
            if (matches.length === 1) options[spec.option] = matches[0].id;
            else if (matches.length > 1) ambiguous.push({ token: raw, candidates: matches });
            else errors.push({ token: raw, message: `No agent named \`${value}\`` });
        } else if (kind === 'user' || kind === 'key' || spec.single) {
            options[spec.option] = value;
        } else {
            options[token.negated ? (spec.negate as string) : spec.option] = values;
        }
    }
    if (parsed.text.length) {
        if (ctx.textOption) options[ctx.textOption] = parsed.text.join(' ');
        else errors.push({ token: parsed.text.join(' '), message: 'Filters are written key:value' });
    }
    return { options, errors, ambiguous };
}

const USER: QueryKeySpec = { kind: 'user', option: 'userFilter' };
const KEY: QueryKeySpec = { kind: 'key', option: 'key' };
const AGENT: QueryKeySpec = { kind: 'agent', option: 'agent' };
const TIME_PRESETS = ['1h', '1d', '1w', '30d'] as const;

export const OPERATION_STATUSES = [
    'queued',
    'running',
    'awaiting_human',
    'succeeded',
    'failed',
    'canceled',
    'expired',
] as const;

/** `Operation.listPage` / `Operation.summary`. `kind:` values come from `meta.operation_kinds`. */
export const OPERATIONS_QUERY: QuerySchema = {
    kind: { option: 'kind' },
    status: { option: 'status', negate: 'statusNot', values: [...OPERATION_STATUSES, 'live'] },
    user: USER,
    key: KEY,
    agent: AGENT,
    since: { kind: 'time', option: 'createdAfter', values: TIME_PRESETS },
    until: { kind: 'time', option: 'createdBefore' },
};

/** `ToolCall.listPage` / `ToolCall.summary`. */
export const TOOL_CALLS_QUERY: QuerySchema = {
    tool: { option: 'tool', single: true },
    status: { option: 'status', single: true, values: ['success', 'error'] },
    source: { option: 'source', single: true, values: ['api', 'agent', 'mcp_server'] },
    agent: AGENT,
    user: USER,
    since: { kind: 'time', option: 'since', values: TIME_PRESETS },
    until: { kind: 'time', option: 'until' },
};

/** `ApiRequest.listPage`. */
export const API_REQUESTS_QUERY: QuerySchema = {
    method: { option: 'method', single: true, values: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE'] },
    status: { option: 'status', single: true, values: ['2xx', '4xx', '5xx'] },
    error: { option: 'errorType', single: true },
    key: KEY,
    route: { option: 'route', single: true },
    user: USER,
    since: { kind: 'time', option: 'since', values: TIME_PRESETS },
    until: { kind: 'time', option: 'until' },
};

export const HUMAN_REQUEST_STATUSES = ['pending', 'answered', 'delivered', 'expired', 'canceled'] as const;

/** `HumanRequest.listPage`. `answerable:you` is what the bell and Overview link to. */
export const HUMAN_REQUESTS_QUERY: QuerySchema = {
    kind: { option: 'kind', values: ['approve', 'ask', 'notify'] },
    status: { option: 'status', negate: 'statusNot', values: HUMAN_REQUEST_STATUSES },
    answerable: { option: 'answerable', single: true, values: ['you'], map: { you: 'owner' } },
    user: USER,
};
