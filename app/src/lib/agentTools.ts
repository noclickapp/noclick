// What an agent can use, read from its `tools` as the platform stores them (GET /v1/agents/{id}): everything on the
// account (`everything`, what an agent made with no tools gets), its apps (a connection by name, `credential:<id>` for
// one connected in the app, `connection:<id>` from another scope, or an integration whose operations need no account,
// each whole or narrowed to some operations), NoClick's own tools (`search`, `fetch`, `browser`, `noclick`, `agents`,
// `card`, each whole or narrowed), the account's resources (`database:<id>`, `bucket:<id>`) and people
// (`{human, tools}`). `code` is the agent's own shell, never listed. Rows group what one thing gives (`gmail` and
// `gmail.send_email` are one Gmail), so removing a row removes every entry of it; under everything, what it already
// gives is one row with it.
import type { Connection, JsonObject } from 'noclick';

/** One entry of `tools` as the platform stores it. */
export type ToolEntry = string | JsonObject;

/** Everything on the account, resolved at each turn: every connection of the agent's scope (ones connected later
 *  too), every app operation that needs no account, the web and NoClick itself, whose part `noclick.<group>` beside it
 *  narrows. */
export const EVERYTHING = 'everything';
/** NoClick's own tools everything gives: the web and NoClick itself. */
export const EVERYTHING_OWN = ['search', 'fetch', 'noclick'] as const;

/** NoClick's own tools: what each gives, in a person's words. */
export const NOCLICK_TOOLS = [
    { ref: 'search', title: 'Search the web', line: 'Finds current pages and cites them' },
    { ref: 'fetch', title: 'Read web pages', line: 'Opens a link and reads what’s on it' },
    { ref: 'browser', title: 'A browser', line: 'Clicks, types and fills in forms on real sites' },
    { ref: 'noclick', title: 'NoClick', line: 'Builds and runs things in your account, asking you before anything that costs' },
    { ref: 'agents', title: 'Your other agents', line: 'Hands work to them and hears back' },
] as const;
const CARD = { ref: 'card', title: 'Its card', line: 'Pays for what it buys' };
const OWN = [...NOCLICK_TOOLS, CARD];

/** What a narrowed entry names, in words: `noclick.build` → build. */
const NARROWED: Record<string, string> = { read: 'read', build: 'build', deploy: 'deploy', spend: 'spend', delete: 'delete', goto: 'open pages', act: 'act on pages', extract: 'read pages', content: 'page text', purchase: 'pay', status: 'status' };

export type ToolRow =
    /** `noclick`: what NoClick's part is narrowed to, in words; null for all of it. */
    | { kind: 'everything'; key: string; entries: ToolEntry[]; noclick: string[] | null }
    | { kind: 'app'; key: string; entries: ToolEntry[]; base: string; connection: Connection | null; operations: string[] | null }
    | { kind: 'noclick'; key: string; entries: ToolEntry[]; ref: string; title: string; line: string }
    | { kind: 'resource'; key: string; entries: ToolEntry[]; title: string; line: string }
    | { kind: 'person'; key: string; entries: ToolEntry[]; title: string; line: string };

const refOf = (entry: ToolEntry): string | null => (typeof entry === 'string' ? entry : typeof entry.tool === 'string' ? entry.tool : null);

/** A ref's first part: `gmail` of `gmail.send_email`, `credential:<id>` of `credential:<id>.list`. */
export const baseOf = (ref: string) => ref.split('.')[0];

const isResource = (base: string) => base.includes(':') && !base.startsWith('credential:') && !base.startsWith('connection:');

/** Whether everything gives all of a ref's `base`: the web, NoClick, and any app but another scope's connection. */
const inEverything = (base: string) =>
    base === EVERYTHING || (EVERYTHING_OWN as readonly string[]).includes(base) || (base !== 'code' && !OWN.some((t) => t.ref === base) && !isResource(base) && !base.startsWith('connection:'));

/** Whether `tools` holds everything on the account. */
export const holdsEverything = (tools: readonly ToolEntry[]) => tools.some((t) => refOf(t) === EVERYTHING);

/** The connection a ref names: by id for `credential:` and `connection:`, else by name. */
export function connectionFor(base: string, connections: readonly Connection[]): Connection | null {
    if (base.startsWith('credential:') || base.startsWith('connection:')) return connections.find((c) => c.id === base || `connection:${c.id}` === base) ?? null;
    return connections.find((c) => c.name === base) ?? null;
}

/** The ref an agent names a connection by: its id when connected in the app, else its name. */
export const refFor = (connection: Connection) => (connection.origin === 'app' ? connection.id : connection.name);

/** Its tools as rows, in the order they were given: everything, apps, then NoClick's own, then resources and people.
 *  Under everything, what it gives (an app of its scope, the web, NoClick narrowed or not) is its row's. */
export function toolRows(tools: readonly ToolEntry[], connections: readonly Connection[]): ToolRow[] {
    const all = holdsEverything(tools);
    const rows = new Map<string, ToolRow>();
    for (const entry of tools) {
        if (typeof entry !== 'string' && entry.human && typeof entry.human === 'object') {
            const human = entry.human as JsonObject;
            const key = `person:${JSON.stringify(human)}`;
            const what = Array.isArray(entry.tools) ? (entry.tools as string[]) : [];
            rows.set(key, { kind: 'person', key, entries: [entry], title: human.owner ? 'You' : String(human.name ?? human.email ?? human.user_id ?? 'A person'), line: personLine(what) });
            continue;
        }
        const ref = refOf(entry);
        if (!ref || ref === 'code') continue;
        const base = baseOf(ref);
        const narrowed = ref.slice(base.length + 1);
        if (all && inEverything(base)) {
            const held = rows.get(EVERYTHING);
            if (held) held.entries.push(entry);
            else rows.set(EVERYTHING, { kind: 'everything', key: EVERYTHING, entries: [entry], noclick: null });
            continue;
        }
        const own = OWN.find((t) => t.ref === base);
        const key = `${own ? 'noclick' : isResource(base) ? 'resource' : 'app'}:${base}`;
        const held = rows.get(key);
        if (held) {
            held.entries.push(entry);
            if (held.kind === 'app') held.operations = held.operations && narrowed ? [...held.operations, narrowed] : null;
            if (held.kind === 'noclick' && held.line.startsWith('Only ')) held.line = narrowed ? `${held.line}, ${NARROWED[narrowed] ?? narrowed}` : own!.line;
            continue;
        }
        if (own) rows.set(key, { kind: 'noclick', key, entries: [entry], ref: base, title: own.title, line: narrowed ? `Only ${NARROWED[narrowed] ?? narrowed}` : own.line });
        else if (key.startsWith('resource:')) rows.set(key, { kind: 'resource', key, entries: [entry], title: base.startsWith('database:') ? 'A database' : base.startsWith('bucket:') ? 'A bucket' : base, line: base.slice(base.indexOf(':') + 1) });
        else rows.set(key, { kind: 'app', key, entries: [entry], base, connection: connectionFor(base, connections), operations: narrowed ? [narrowed] : null });
    }
    const everything = rows.get(EVERYTHING);
    if (everything?.kind === 'everything') {
        // NoClick is all of it unless only narrower entries name it.
        const noclick = everything.entries.map(refOf).filter((r): r is string => !!r && baseOf(r) === 'noclick');
        if (noclick.length && !noclick.includes('noclick')) everything.noclick = noclick.map((r) => r.slice('noclick.'.length)).map((n) => NARROWED[n] ?? n);
    }
    const order = { everything: 0, app: 1, noclick: 2, resource: 3, person: 4 };
    return [...rows.values()].sort((a, b) => order[a.kind] - order[b.kind]);
}

function personLine(tools: string[]): string {
    const can = tools.map((t) => (t === 'notify' ? 'tell' : t === 'ask' ? 'ask' : t === 'handoff' ? 'hand over to' : t));
    return can.length ? `It can ${new Intl.ListFormat('en', { type: 'conjunction' }).format(can)} them` : 'It can reach them';
}

const same = (a: ToolEntry, b: ToolEntry) => JSON.stringify(a) === JSON.stringify(b);

/** `tools` without a row's entries. */
export const without = (tools: readonly ToolEntry[], row: ToolRow): ToolEntry[] => tools.filter((t) => !row.entries.some((e) => same(e, t)));

/** `tools` giving all of `ref` (an app's connection, one of NoClick's own, or everything): any narrower entry of it goes. */
export function withAll(tools: readonly ToolEntry[], ref: string): ToolEntry[] {
    const kept = tools.filter((t) => {
        const r = refOf(t);
        return !r || baseOf(r) !== ref;
    });
    return [...kept, ref];
}

/** NoClick's capability groups, which an agent's rules narrow (`noclick.<group>`) where its tools once did. */
const NOCLICK_GROUPS = ['read', 'build', 'deploy', 'spend', 'delete'];

/** `tools` holding everything in place of what everything covers (apps, the web, NoClick and its groups), so rules
 *  narrow it instead: people, resources, a browser, another scope's connection, a bound operation, NoClick's API areas
 *  and its shell stay. A list of tools turned into Work's Restricted this way keeps what it reached, its rules saying
 *  which apps are on. */
export function toEverything(tools: readonly ToolEntry[]): ToolEntry[] {
    const kept = tools.filter((t) => {
        if (typeof t !== 'string') return true;
        const base = baseOf(t);
        if (base === 'noclick') return t.length > base.length && !NOCLICK_GROUPS.includes(t.slice(base.length + 1));
        return !inEverything(base);
    });
    return [EVERYTHING, ...kept];
}

/** Whether `tools` gives all of `ref`, or any of it (everything gives what it covers). */
export function holds(tools: readonly ToolEntry[], ref: string): boolean {
    if (holdsEverything(tools) && inEverything(baseOf(ref))) return true;
    return tools.some((t) => {
        const r = refOf(t);
        return !!r && baseOf(r) === ref;
    });
}

/** The header an MCP server's key goes in: Authorization unless another is named, where a bare key is a bearer token
 *  (a value with a space already names its scheme, as `token abc` or `Basic …` do). */
export function keyHeaders(key: string, header: string): Record<string, string> {
    const name = header.trim() || 'Authorization';
    const value = key.trim();
    return { [name]: name.toLowerCase() === 'authorization' && !/\s/.test(value) ? `Bearer ${value}` : value };
}
