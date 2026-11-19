// What an agent's call is doing, in words, named by what it called: a /v1 operation by its summary (the names
// api_describe answers with), NoClick finding its way as looking into it, an app the person connected by the app's own
// name ("Read an email thread in Gmail"), and a service NoClick picks and pays for by what it did, never its name
// ("Searched the web"). A running call reads as happening now ("Listing workflows"), a finished one as done ("Listed
// workflows"), and `base` is the bare action, for saying what couldn't be done ("couldn't read run"). The names come
// from NoClick's API (operationLabels.generated.ts); an app's own name from the node catalog the host hands in
// (nodeIconRegistry), else its tools' namespace.
import { AGENT_TOOL_APPS, OPERATIONS, PLATFORM_TOOL_TITLES, PLATFORM_VENDOR_OPERATIONS } from '@/lib/operationLabels.generated';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';

export type StepPhase = 'running' | 'done' | 'base';
/** What a call does to the world, for how it's drawn: the operation's risk class, or a search. */
export type StepKind = 'search' | 'read' | 'write' | 'spend' | 'destructive' | 'outbound';

export interface StepName {
    /** What it did, said on its own ("Searched the web"): what a summary of the turn says. */
    label: string;
    /** What it was about (a search's words, the page it read, the name it used), when the call says. */
    detail?: string;
    /** The words the detail completes ("Searched the web for" “…”); without them the detail follows the label after a
     *  dot. */
    lead?: string;
    kind: StepKind;
}

/** A call's line in two parts, so the detail gives way first in a narrow column: "Searched the web for" + " “…”", or
 *  "Listed workflows" + " · coordinator". */
export function stepLine(name: StepName): { head: string; tail?: string } {
    if (!name.detail) return { head: name.label };
    return name.lead ? { head: name.lead, tail: `\u00a0${name.detail}` } : { head: name.label, tail: `\u00a0·\u00a0${name.detail}` };
}

const PLATFORM_PREFIX = 'noclick__';
// How a coding harness names a tool of NoClick's MCP server: "mcp__noclick__api_call", or "mcp__nc__api_call" where
// a sandbox NoClick runs reaches NoClick's own tools under that name.
const HARNESS_PREFIX = /^mcp__(?:noclick|nc)__/;

// English verbs these names start with. The API's own verb reads as people say it where they differ (Get or Fetch →
// reading, Put → saving, Exec → running), and each is inflected by rule unless it's irregular.
const SAID_AS: Record<string, string> = {
    get: 'read', fetch: 'read', retrieve: 'read', scrape: 'read', show: 'read', put: 'save', exec: 'run', patch: 'update', spawn: 'start',
    lookup: 'look up',
};
const IRREGULAR_PAST: Record<string, string> = {
    buy: 'bought', build: 'built', find: 'found', hide: 'hid', run: 'ran', send: 'sent', set: 'set', read: 'read', write: 'wrote', reset: 'reset', make: 'made', put: 'put',
};
const STRESSED_LAST = new Set(['commit', 'transfer', 'submit', 'admit', 'refer', 'embed', 'unban', 'unpin']);
const VERBS = new Set([
    'accept', 'activate', 'add', 'aggregate', 'alter', 'analyze', 'answer', 'append', 'apply', 'approve', 'archive', 'ask', 'assign',
    'attach', 'build', 'buy', 'call', 'cancel', 'capture', 'change', 'check', 'clear', 'close', 'commit', 'compose', 'confirm', 'connect',
    'convert', 'copy', 'count', 'create', 'deactivate', 'delete', 'deploy', 'describe', 'detach', 'disable', 'discard', 'download', 'drop',
    'duplicate', 'edit', 'embed', 'enable', 'enrich', 'evaluate', 'exec', 'export', 'extract', 'fetch', 'find', 'follow', 'generate', 'get',
    'hand', 'hide', 'import', 'increment', 'insert', 'invite', 'invoke', 'list', 'look', 'lookup', 'make', 'mark', 'merge', 'message',
    'move', 'mute', 'notify', 'open', 'patch', 'pause', 'pick', 'pin', 'place', 'post', 'price', 'publish', 'put', 'query', 'read',
    'receive', 'refund', 'reject', 'release', 'remove', 'rename', 'reply', 'request', 'require', 'research', 'reschedule', 'reset',
    'restore', 'resume', 'retrieve', 'retry', 'revoke', 'rotate', 'run', 'save', 'scan', 'schedule', 'scrape', 'search', 'send', 'set',
    'share', 'show', 'spawn', 'start', 'stop', 'submit', 'subscribe', 'suspend', 'sync', 'test', 'transfer', 'translate', 'trash',
    'unban', 'unfollow', 'unpin', 'unschedule', 'unset', 'unsubscribe', 'update', 'upload', 'upsert', 'validate', 'verify', 'wait', 'write',
]);
const KIND_OF_VERB: Record<string, StepKind> = {
    search: 'search', find: 'search', look: 'search', query: 'search',
    buy: 'spend', price: 'spend',
    delete: 'destructive', remove: 'destructive', revoke: 'destructive', cancel: 'destructive', trash: 'destructive', discard: 'destructive',
    send: 'outbound', call: 'outbound', place: 'outbound', message: 'outbound', notify: 'outbound', ask: 'outbound', post: 'outbound', reply: 'outbound',
};
const READS = new Set(['list', 'get', 'read', 'check', 'describe', 'fetch', 'open', 'lookup', 'evaluate', 'wait', 'scrape', 'retrieve', 'download', 'count', 'scan']);
// Acronyms the API's generated titles spell as words.
const SPELLED: Record<string, string> = {
    url: 'URL', rpc: 'RPC', dns: 'DNS', api: 'API', a2a: 'A2A', noclick: 'NoClick', github: 'GitHub', sms: 'SMS', id: 'ID', ids: 'IDs',
    json: 'JSON', csv: 'CSV', pdf: 'PDF', html: 'HTML', dm: 'DM', ai: 'AI', acl: 'ACL', iam: 'IAM', ldap: 'LDAP', db: 'DB',
};

const VOWEL = /[aeiou]/;

const bare = (w: string) => w.toLowerCase().replace(/[^a-z]/g, '');

function doubles(verb: string): boolean {
    if (STRESSED_LAST.has(verb)) return true;
    // One syllable ending consonant-vowel-consonant (get, set, stop, run), never in w, x or y.
    return /^[^aeiou]*[aeiou][^aeiouwxy]$/.test(verb);
}

function inflect(verb: string, phase: StepPhase): string {
    const [head, ...tail] = verb.split(' ');
    const rest = tail.length ? ` ${tail.join(' ')}` : '';
    if (phase === 'base') return verb;
    if (phase === 'done') {
        if (IRREGULAR_PAST[head]) return IRREGULAR_PAST[head] + rest;
        if (head.endsWith('e')) return `${head}d${rest}`;
        if (/[^aeiou]y$/.test(head)) return `${head.slice(0, -1)}ied${rest}`;
        return `${head}${doubles(head) ? head.slice(-1) : ''}ed${rest}`;
    }
    if (head.endsWith('ie')) return `${head.slice(0, -2)}ying${rest}`;
    if (head.endsWith('e') && !head.endsWith('ee') && VOWEL.test(head.slice(0, -1))) return `${head.slice(0, -1)}ing${rest}`;
    return `${head}${doubles(head) ? head.slice(-1) : ''}ing${rest}`;
}

function sentence(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function word(w: string): string {
    const lower = w.toLowerCase();
    return SPELLED[lower] ?? (w === w.toUpperCase() && /[A-Z]/.test(w) ? w : lower);
}

/** "List Workflows" → "Listing workflows" / "Listed workflows". A name that starts with no verb (a namespace, like
 *  "credential place call") starts at its first verb; one with none at all reads as it is. */
export function verbPhrase(name: string, phase: StepPhase): string {
    const words = name.trim().split(/\s+/).filter(Boolean);
    const at = words.findIndex((w) => VERBS.has(bare(w)));
    if (at < 0) return sentence(words.map(word).join(' '));
    // A run of verbs ("Delete, cancel or revoke") is all one action: each is inflected, keeping its punctuation.
    const joins = (w: string) => /^(or|and)$/i.test(w);
    let end = at + 1;
    while (
        end < words.length &&
        ((joins(words[end]) && VERBS.has(bare(words[end + 1] ?? ''))) || (VERBS.has(bare(words[end])) && (words[end - 1].endsWith(',') || joins(words[end - 1]))))
    )
        end++;
    const said = words.slice(at, end).map((w) => {
        const verb = bare(w);
        return VERBS.has(verb) ? inflect(SAID_AS[verb] ?? verb, phase) + w.slice(w.search(/[^A-Za-z]*$/)) : w.toLowerCase();
    });
    return sentence([...said, ...words.slice(end).map(word)].join(' '));
}

/** Long work's kind ("project.deploy") as its action ("Deployed", "Deploy"), when its last word is one. */
export function kindVerb(kind: string, phase: StepPhase): string | undefined {
    const verb = bare(kind.split(/[._]/).pop() ?? '');
    return VERBS.has(verb) ? verbPhrase(verb, phase) : undefined;
}

function kindOf(name: string): StepKind {
    const verb = name.trim().split(/\s+/).map(bare).find((w) => VERBS.has(w));
    if (!verb) return 'read';
    return KIND_OF_VERB[verb] ?? (READS.has(verb) ? 'read' : 'write');
}

const RISK_KIND: Record<string, StepKind> = { read: 'read', write: 'write', spend: 'spend', destructive: 'destructive', outbound: 'outbound' };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A value worth showing beside the label: words, never an id. */
function shown(value: unknown): string | undefined {
    if (typeof value !== 'string') return undefined;
    const text = value.trim();
    if (!text || UUID.test(text) || /^id_\d+$/.test(text)) return undefined;
    return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

/** A ref (`workflow:<id>`, `guide:apps#create-an-app`) as a person reads it. */
function refShown(ref: unknown): string | undefined {
    if (typeof ref !== 'string') return undefined;
    const [kind, rest = ''] = ref.split(':');
    if (!rest) return shown(ref);
    const name = rest.split('#')[0].replace(/[-_]+/g, ' ');
    return UUID.test(rest) || /^id_\d+$/.test(rest) ? `a ${kind}` : `the ${name} ${kind}`;
}

function operationName(name: unknown, phase: StepPhase): { label: string; kind: StepKind } | undefined {
    if (typeof name !== 'string' || !OPERATIONS[name]) return undefined;
    const [summary, method, risk] = OPERATIONS[name];
    const starts = VERBS.has(bare(summary.split(' ')[0]));
    // A summary that names no action ("Project Logs") is read when the call only reads.
    const label = starts || method !== 'GET' ? verbPhrase(summary, phase) : verbPhrase(`read ${summary}`, phase);
    return { label, kind: RISK_KIND[risk] ?? 'read' };
}

const NAMED_BY = ['name', 'query', 'title', 'domain', 'to', 'branch', 'subject'];

type Args = Record<string, unknown> | undefined;

const inner = (args: Args) => (args?.arguments ?? args) as Args;

function argument(args: Args): string | undefined {
    for (const key of NAMED_BY) {
        const value = shown(inner(args)?.[key]);
        if (value) return value;
    }
    return undefined;
}

/** Words it looked for, as they were typed. */
function quoted(value: unknown): string | undefined {
    const text = shown(value);
    return text && `“${text}”`;
}

/** The pages it read as a person reads an address ("github.com/openai/codex"), and how many more. */
function pages(value: unknown): string | undefined {
    const urls = (Array.isArray(value) ? value : typeof value === 'string' ? value.split(/[\s,]+/) : []).flatMap((u) => {
        const at = typeof u === 'string' ? /^https?:\/\/(?:www\.)?([^?#\s]+)/i.exec(u) : null;
        return at ? [at[1].replace(/\/+$/, '')] : [];
    });
    if (!urls.length) return undefined;
    return `${shown(urls[0])}${urls.length > 1 ? ` and ${urls.length - 1} more` : ''}`;
}

/** A step with the words its detail completes, said only when there is a detail. */
function phrased(label: string, lead: string, detail: string | undefined, kind: StepKind): StepName {
    return detail ? { label, lead, detail, kind } : { label, kind };
}

// NoClick finding its way (its docs, its API, the account's things), recalling, and looking for an app: said as what
// they're for, whatever each looked at.
const RECALL = { label: 'check what it remembers', lead: 'check what it remembers about', kind: 'search' } as const;
const OWN: Record<string, { label: string; lead: string; kind: StepKind }> = {
    search: { label: 'look into it', lead: 'look up', kind: 'search' },
    api_describe: { label: 'look into it', lead: 'look up', kind: 'read' },
    fetch: { label: 'look into it', lead: 'read', kind: 'read' },
    search_memories: RECALL,
    memory__search: RECALL,
    search_credential_tools: { label: 'look for the right app', lead: 'look for an app for', kind: 'search' },
};

// A browser's calls, said as what happens on the page (the page it opens by its address, never the browser's id):
// NoClick's call of the browser API (`browsers_goto`) or an agent's own browser tool (`browser__goto`). The catalog's
// names for them are its routes' ("Goto", "Page Content"), which say nothing to a person watching.
const BROWSER: Record<string, { label: string; lead?: string; detail?: (args: Args) => string | undefined; kind: StepKind }> = {
    create: { label: 'start a browser', kind: 'write' },
    goto: { label: 'open a page', lead: 'open', detail: (args) => pages(inner(args)?.url), kind: 'read' },
    content: { label: 'read the page', kind: 'read' },
    extract: { label: 'read the page', lead: 'read off the page', detail: (args) => quoted(inner(args)?.query), kind: 'read' },
    screenshot: { label: 'look at the page', kind: 'read' },
    act: { label: 'run a task in the browser', detail: (args) => shown(inner(args)?.instruction), kind: 'outbound' },
};

function browserStep(name: string, args: Args, phase: StepPhase): StepName | null {
    const operation = name === 'api_call' && typeof args?.operation === 'string' ? /^browsers_(\w+)$/.exec(args.operation)?.[1] : /^browser__(\w+)$/.exec(name)?.[1];
    const said = operation ? BROWSER[operation] : undefined;
    if (!said) return null;
    const detail = said.detail?.(args);
    return said.lead ? phrased(verbPhrase(said.label, phase), verbPhrase(said.lead, phase), detail, said.kind) : { label: verbPhrase(said.label, phase), detail, kind: said.kind };
}

// What a service NoClick picks and pays for did, by its operation's own verb: a search searches the web, a read reads a
// page, anything else researches a question. The service is never named; nobody chose it.
const BOUGHT = {
    search: { label: 'search the web', lead: 'search the web for' },
    read: { label: 'read a web page', lead: 'read' },
    research: { label: 'research a question', lead: 'research' },
};

function bought(operation: string, args: Args, phase: StepPhase): StepName {
    const verb = operation.split('_').find((w) => VERBS.has(w));
    const work = verb && KIND_OF_VERB[verb] === 'search' ? 'search' : verb && READS.has(verb) ? 'read' : 'research';
    const words = quoted(inner(args)?.query ?? inner(args)?.prompt);
    const read = pages(inner(args)?.urls ?? inner(args)?.url);
    const { label, lead } = BOUGHT[work];
    return phrased(verbPhrase(label, phase), verbPhrase(lead, phase), work === 'read' ? (read ?? words) : (words ?? read), 'search');
}

// Words that make a thing definite ("the newest stories"), words that already say which ("your profile", "all"), and
// words said with no article: a mass, or a particle ("hand back").
const DEFINITE = new Set(['newest', 'latest', 'oldest', 'recent', 'current', 'top', 'first', 'last', 'next', 'previous', 'authenticated']);
const DETERMINERS = new Set(['your', 'my', 'our', 'their', 'its', 'all', 'many', 'multiple', 'each', 'every', 'some', 'any']);
const BARE = new Set(['data', 'metadata', 'info', 'information', 'content', 'contents', 'analytics', 'usage', 'media', 'feedback', 'history', 'advice', 'back', 'on', 'off', 'up', 'out']);
const PREPOSITIONS = new Set(['to', 'in', 'on', 'for', 'from', 'by', 'with', 'of', 'into', 'at', 'as']);
// An object's word as people say it ("get_me" reads your account).
const OBJECT_SAID: Record<string, string> = { me: 'your account' };

/** The article a thing takes, by its head noun (its last word before any preposition): "the" when a word makes it
 *  definite, none when a word already says which, or it's many ("stories") or a mass ("metadata"), else "a" or "an". */
function articleOf(object: string[]): string {
    if (!object.length || DETERMINERS.has(object[0])) return '';
    if (DEFINITE.has(object[0])) return 'the';
    const end = object.findIndex((w, i) => i > 0 && PREPOSITIONS.has(w));
    const noun = object[(end < 0 ? object.length : end) - 1].toLowerCase();
    if (BARE.has(noun) || /[^siu]s$/.test(noun)) return '';
    const first = object[0];
    // An acronym is said letter by letter ("an API", "a URL").
    if (first.length > 1 && first === first.toUpperCase()) return /^[AEFHILMNORSX]/.test(first) ? 'an' : 'a';
    return /^([aeio]|u(?![bcfhjklmnprstv][aeiouy]))/i.test(first) ? 'an' : 'a';
}

/** An app's operation as a sentence, the app named as it names itself: one thing in it ("Read an email thread in
 *  Gmail"), the app's own things ("Listed Slack teams", "Read the newest Hacker News stories"), and a search with what
 *  it looked for ("Searched Google Drive files for “…”"). */
function appStep(app: string, operation: string, args: Args, phase: StepPhase): StepName {
    const [verb, ...rest] = operation.split('_').filter(Boolean);
    // An operation says what it does with its first word; one that doesn't is said as it's named.
    if (!VERBS.has(verb)) return { label: sentence(`${[verb, ...rest].map(word).join(' ')} in ${app}`), detail: argument(args), kind: 'read' };
    const words = rest.flatMap((w) => (OBJECT_SAID[w] ?? word(w)).split(' '));
    // Words that lead with a preposition keep it ahead of the thing ("reply to an email message").
    const starts = words.findIndex((w) => !PREPOSITIONS.has(w));
    const to = starts < 0 ? words : words.slice(0, starts);
    const object = starts < 0 ? [] : words.slice(starts);
    const kind = KIND_OF_VERB[verb] ?? (READS.has(verb) ? 'read' : 'write');
    const did = inflect(SAID_AS[verb] ?? verb, phase);
    const article = articleOf(object);
    const definite = article === 'the' ? object.findIndex((w) => !DEFINITE.has(w)) : 0;
    // A list is of the app's things whatever its word ("Slack custom emoji"); so are many things, or a mass.
    const theApps = !to.length && (verb === 'list' || (!article && !DETERMINERS.has(object[0])));
    const said =
        article === 'the'
            ? [did, ...to, 'the', ...object.slice(0, definite), app, ...object.slice(definite)]
            : !object.length
              ? [did, ...to, ...(kind === 'search' || verb === 'list' ? [] : ['in']), app]
              : theApps
                ? [did, app, ...object]
                : [did, ...to, ...(article ? [article] : []), ...object, 'in', app];
    const label = sentence(said.join(' '));
    if (kind !== 'search') return { label, detail: argument(args), kind };
    return phrased(label, `${label} for`, quoted(inner(args)?.query) ?? argument(args), kind);
}

/** The app a tool's namespace is, by the name the app goes by ("google_drive" → "Google Drive"). */
function appOf(namespace: string): { slug: string; name: string } | undefined {
    const slug = namespace.replace(/_/g, '-');
    if (!AGENT_TOOL_APPS.has(slug)) return undefined;
    return { slug, name: getNodeIconMeta(`automation-${slug}`)?.label ?? namespace.split('_').map((w) => sentence(word(w))).join(' ') };
}

/** The words for a call NoClick knows by name (its own tools, an app's operations, a search it buys); null for a tool
 *  it can only guess at from its name. */
export function knownStepName(tool: string, args: Args, phase: StepPhase): StepName | null {
    const unprefixed = tool.replace(HARNESS_PREFIX, '');
    const name = unprefixed.startsWith(PLATFORM_PREFIX) ? unprefixed.slice(PLATFORM_PREFIX.length) : unprefixed;
    const browser = browserStep(name, args, phase);
    if (browser) return browser;
    // A call that names its operation (call it, delete with it) reads as that operation.
    if (name === 'api_call' || name === 'delete') {
        const op = operationName(args?.operation, phase);
        if (op) return { ...op, detail: argument(args) };
    }
    if (name === 'api_describe' && typeof args?.operation === 'string' && OPERATIONS[args.operation]) {
        const [verb, ...object] = OPERATIONS[args.operation][0].split(' ').map(word);
        const how = VERBS.has(bare(verb)) ? [verbPhrase('check', phase), 'how to', verb, articleOf(object), ...object] : [verbPhrase('look up', phase), verb, ...object];
        return { label: how.filter(Boolean).join(' '), kind: 'read' };
    }
    const own = OWN[name];
    if (own) {
        // Reading a ref reads as what it read ("Reading the apps guide").
        const detail = name === 'fetch' ? refShown(args?.id) : quoted(args?.query);
        return phrased(verbPhrase(own.label, phase), verbPhrase(own.lead, phase), detail, own.kind);
    }
    const title = PLATFORM_TOOL_TITLES[name];
    if (title) {
        const named = typeof args?.operation === 'string' ? OPERATIONS[args.operation]?.[0] : undefined;
        return { label: verbPhrase(title, phase), detail: named ?? argument(args), kind: kindOf(title) };
    }
    // `app__operation` is an app's: one NoClick buys says what it did, one the person connected names the app.
    const [namespace, ...rest] = name.split('__');
    const operation = rest.join('__');
    const app = operation ? appOf(namespace) : undefined;
    if (app) return PLATFORM_VENDOR_OPERATIONS[app.slug]?.includes(operation) ? bought(operation, args, phase) : appStep(app.name, operation, args, phase);
    if (name === 'web_search') return bought('search', args, phase);
    return null;
}

/** The words for one call. `tool` as the agent named it (`noclick__api_call`, `memory__search`, `find_connections`). */
export function stepName(tool: string, args: Args, phase: StepPhase): StepName {
    const known = knownStepName(tool, args, phase);
    if (known) return known;
    // Any other tool: `namespace__operation` reads as its operation on its namespace, a plain name as itself; a
    // trailing hash some tool names carry is no word.
    const [namespace, ...rest] = (tool.startsWith(PLATFORM_PREFIX) ? tool.slice(PLATFORM_PREFIX.length) : tool).split('__');
    const words = (rest.length ? `${rest.join(' ')} ${namespace}` : namespace).replace(/_[0-9a-f]{8,}$/i, '').replace(/[_-]+/g, ' ');
    return { label: verbPhrase(words, phase), detail: argument(args), kind: kindOf(words) };
}
