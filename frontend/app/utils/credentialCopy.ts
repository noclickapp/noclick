// What a way of connecting an app says to a person, derived from the credential schema alone so it reads the same for
// every provider: a name for the way in ("Sign in with Notion", "Integration token"), one plain line about it, how to
// get the value (the schema's x-credential-instructions, else the steps in its description) and where (the
// x-credential-url's host, never the raw URL). A schema description is written for developers ("OAuth 2.0 credential
// for Notion. Tokens are obtained via OAuth flow…"), so it is never shown as is: only its instructions survive.
// Every credential in the node schemas is pinned in tests/utils/__snapshots__/credential-copy.snap.txt.
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { kindFromBackendMethod, type CredentialMethodKind } from '~/lib/credentialMethodKind';
import { fixWordCasing } from '~/utils/credentialLabels';

/** The parts of a way in that its copy reads (a backend method and a schema-built one both have them). */
export interface CopyMethod {
    kind: CredentialMethodKind;
    /** Humanized class label, e.g. "Notion Integration Token". */
    label: string;
    description?: string | null;
    instructions?: string | null;
    credentialUrl?: string | null;
    requiresCustomClient?: boolean;
    fields?: CopyField[];
}

export interface CopyField {
    label: string;
    /** "password" for a masked value. */
    type?: string;
    placeholder?: string;
    description?: string | null;
    helpUrl?: string | null;
    required?: boolean;
}

export interface MethodCopy {
    /** The way in, as a person names it: "Sign in with Notion", "Integration token". */
    name: string;
    /** One plain sentence about it. */
    line: string;
    /** How to get the value, in the provider's own steps; null when the schema has none. */
    howTo: string | null;
    /** Where the value comes from. */
    source: SourceLink | null;
}

/** A way in (a provide link's backend method, or one built from a node schema) as the copy reads it. */
export function copyMethodOf(method: ProvideCredentialMethod): CopyMethod {
    return {
        kind: kindFromBackendMethod(method),
        label: method.label,
        description: method.description,
        instructions: method.instructions,
        credentialUrl: method.credential_url,
        requiresCustomClient: method.requires_custom_client,
        fields: method.credential_fields,
    };
}

export interface SourceLink {
    href: string;
    /** "notion.so", "dashboard.stripe.com" */
    host: string;
}

// Credential vocabulary set in sentence case ("App Password" → "App password"); anything else (a brand, an acronym)
// keeps its casing.
const GENERIC_WORDS = new Set(
    (
        'access account accounts and app application auth bearer bot client connection credential credentials ' +
        'database developer email handle host id integration internal key keys login management or page partner password ' +
        'personal port private project read region secret server service site standard string subdomain system team to ' +
        'token tokens url user username with workspace only organization domain install number phone code name ' +
        'base instance cluster endpoint webhook signing live test admin primary secondary expiry allowed resource origin ' +
        'send in custom headers header authentication type method mode uri scope audience refresh web version ' +
        'slug identifier feed store company tenant'
    ).split(' ')
);

const ACRONYMS: Record<string, string> = {
    PAT: 'personal access token',
    PIT: 'private integration token',
};

const STOP_WORDS = new Set(['your', 'the', 'a', 'an', 'from', 'for', 'of', 'to', 'in', 'this', 'that', 'is', 'used', 'value', 'not', 'address']);

function words(text: string): string[] {
    return text.split(/\s+/).filter(Boolean);
}

const isAcronym = (word: string) => word.length >= 2 && word === word.toUpperCase() && /[A-Z]/.test(word);

/** "Handle or Email" → "Handle or email", "API Key" → "API key"; brands and acronyms keep their casing. */
export function sentenceCase(label: string): string {
    const out = words(label).map((word, i) => {
        const bare = word.toLowerCase();
        if (i > 0 && GENERIC_WORDS.has(bare) && !isAcronym(word)) return bare;
        return word;
    });
    const text = fixWordCasing(out.join(' '));
    return text.charAt(0).toUpperCase() + text.slice(1);
}

const compact = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, '');

/** A method's label without the app's name in front: "Notion Integration Token" for Notion → "Integration Token". */
export function withoutAppName(label: string, app: string): string {
    const tokens = words(label);
    const target = compact(app);
    for (let i = 0; i < tokens.length; i++) {
        const prefix = compact(tokens.slice(0, i + 1).join(''));
        if (prefix === target) return tokens.slice(i + 1).join(' ');
        if (!target.startsWith(prefix)) break;
    }
    // "Twilio API Key" under "Twilio SendGrid": the app's first word is still the app.
    const first = compact(tokens[0] ?? '');
    return first.length > 2 && first === compact(words(app)[0] ?? '') ? tokens.slice(1).join(' ') : label;
}

/** "an app password", "a personal access token", "an API key". */
export function withArticle(noun: string): string {
    const first = words(noun)[0] ?? '';
    const vowelSound = isAcronym(first) ? /^[AEFHILMNOSX]/.test(first) : /^[aeiou]/i.test(first);
    return `${vowelSound ? 'an' : 'a'} ${noun}`;
}

function listOf(items: string[]): string {
    if (items.length <= 1) return items[0] ?? '';
    return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

const requiredLabels = (method: CopyMethod) => (method.fields ?? []).filter((f) => f.required).map((f) => lowerFirst(fieldLabel(f)));

/** A value kept secret: masked, or named a key, token, secret or password. */
const isSecret = (field: CopyField) => field.type === 'password' || /\b(key|token|secret|password|json)\b/i.test(field.label);

/** Who issues the value: the app, unless the way in is named after another brand whose site it comes from (RSS's
 *  "Feedly" token comes from feedly.com). */
function issuer(method: CopyMethod, app: string): string {
    const rest = withoutAppName(method.label, app).replace(/\bCredentials?\b/g, '').trim();
    const brand = !!rest && words(rest).every((w) => /^[A-Z]/.test(w) && !GENERIC_WORDS.has(w.toLowerCase()));
    return brand && compact(sourceLink(method)?.host ?? '').includes(compact(rest)) ? rest : app;
}

// A noun names a thing you paste when it says what kind of value it is; "Basic auth", "Script" or "Read only" name a
// way of signing in, so the line names the fields instead.
const A_THING = /\b(token|key|password|secret|string|sid|url|uri|json|account)\b/i;

/** What you paste, as a noun: the label without the app ("Integration token"), PAT spelled out, or the fields it
 *  asks for when the label names nothing but the app ("Account" → "Account SID and auth token"). */
export function keyNoun(method: CopyMethod, app: string): string {
    let rest = withoutAppName(method.label, app).replace(/\bCredentials?\b/g, '').trim();
    rest = words(rest)
        .map((w) => ACRONYMS[w] ?? w)
        .join(' ');
    if (!rest || /^(account|standard)$/i.test(rest)) {
        // Named after the secret when none of the values it requires is one (Chroma's tenant and database beside its
        // token), else by what it requires ("Account SID and auth token").
        const fields = method.fields ?? [];
        const secret = fields.find(isSecret);
        if (secret && !fields.some((f) => f.required && isSecret(f))) return fieldLabel(secret);
        const required = requiredLabels(method);
        if (required.length) return capitalize(listOf(required));
        return rest ? sentenceCase(rest) : 'Key';
    }
    return sentenceCase(rest);
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export function methodName(method: CopyMethod, app: string, provider = app): string {
    switch (method.kind) {
        case 'oauth':
            return `Sign in with ${provider}`;
        case 'agent_oauth':
            return 'Sign in with your plan';
        case 'qr_scan':
            return 'Scan a QR code';
        case 'purchase':
            return 'Buy a number';
        default: {
            // One value to paste is named as its own field is, so the switch to it and the form agree; when that value
            // is an address beside the secret (Weaviate's cluster URL and API key), the tab is the secret's.
            const fields = method.fields ?? [];
            const required = fields.filter((f) => f.required);
            const secrets = fields.filter(isSecret);
            if (required.length === 1) return fieldLabel(isSecret(required[0]) || !secrets.length ? required[0] : secrets[0]);
            return keyNoun(method, app);
        }
    }
}

export function methodLine(method: CopyMethod, app: string, provider = app): string {
    switch (method.kind) {
        case 'oauth':
            return method.requiresCustomClient
                ? `Signs in through your own ${provider} OAuth app.`
                : `Opens ${provider} to sign in. NoClick never sees your password.`;
        case 'agent_oauth':
            return `Uses your ${app} subscription, so nothing is billed per call.`;
        case 'qr_scan':
            return `Scan a code with ${app} on your phone.`;
        case 'purchase':
            return 'Pick a number and see its price before you buy it.';
        default: {
            const required = requiredLabels(method);
            // One value to paste is named by its own field ("an internal integration token"); several by the key's name,
            // or by the fields themselves when that name is a kind of sign-in rather than a thing, or when none of
            // them is the secret. A key no provider issues (an HTTP request's own header, a database's password) comes
            // from nowhere to name; one another brand issues comes from it.
            const issued = !!sourceLink(method);
            const by = issuer(method, app);
            const from = issued ? ` from ${by}` : '';
            const requiredFields = (method.fields ?? []).filter((f) => f.required);
            if (!required.length) return 'Nothing here is required: fill in only what applies.';
            // The tab is named after a secret beside the values it requires (Chroma's token, Weaviate's key): so is the line.
            const secret = (method.fields ?? []).find(isSecret);
            if (secret && !requiredFields.some(isSecret) && methodName(method, app, provider) === fieldLabel(secret)) {
                return `Paste ${withArticle(lowerFirst(fieldLabel(secret)))}${from} and enter the ${listOf(required)}.`;
            }
            if (required.length === 1) return isSecret(requiredFields[0]) ? `Paste ${withArticle(required[0])}${from}.` : `Enter the ${required[0]}${issued ? ` for ${by}` : ''}.`;
            const noun = keyNoun(method, app);
            const listed = noun.toLowerCase() === listOf(required).toLowerCase();
            if (listed || !A_THING.test(noun) || !requiredFields.some(isSecret)) return `Enter the ${listOf(required)}${issued ? ` for ${by}` : ''}.`;
            return `Paste ${withArticle(lowerFirst(noun))}${from}.`;
        }
    }
}

/** A label mid-sentence: "Jira site" stays, "Store name" reads "store name", "Company Subdomain" reads "company subdomain". */
export function inSentence(label: string): string {
    return lowerFirst(sentenceCase(label));
}

/** Lower-case the first word when it is credential vocabulary ("Personal access token"), never a brand or an acronym
 *  ("Firebase ID token", "API key"). */
function lowerFirst(text: string): string {
    const first = words(text)[0] ?? '';
    return GENERIC_WORDS.has(first.toLowerCase()) && !isAcronym(first) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

// ── Instructions out of a developer description ──────────────────────────────────────────────────────────────────────

const URL_RE = /https?:\/\/[^\s)'"`]+/g;
// A class describing itself ("OAuth 2.0 credential for Notion.", "Bearer token authentication").
const SELF_DESCRIPTION =
    /\b(credentials?|authentication|auth)\s+(for|to|structure)\b|\bcredentials?\s*\(|^(oauth|bearer|basic)\b|tokens are obtained|not entered manually|register (an? )?(oauth|connect) app|authentication$|^api key (authentication|credential)/i;
// Sentences that tell you what to do.
const STEP_START = /^(create|generate|go|open|navigate|copy|share|enable|click|select|add|find|obtain|mint|sign|then|in|from|under|visit|get|turn|install|choose|log|set)\b/i;
// A URL a person goes to ("at: <url>", "(<url>)"); a local one ("Set redirect uri to http://localhost:8080") is a value
// they type.
const POINTED_URL = /\(\s*(https?:\/\/(?!localhost|127\.0\.0\.1)[^\s)]+)\s*\)|\b(?:at|from|here|via|see|visit|to)\s*:?\s*(https?:\/\/(?!localhost|127\.0\.0\.1)[^\s)'"`]+)/i;

function cleanMarkup(text: string): string {
    return text
        .replace(/\*\*/g, '')
        .replace(/`+/g, '')
        .replace(/\s*->\s*/g, ' → ')
        .replace(/\s+/g, ' ')
        .trim();
}

function sentencesOf(text: string): string[] {
    const units: string[] = [];
    let open = false;
    for (const raw of text.replace(/\r/g, '').split('\n')) {
        const line = raw.trim();
        if (!line) {
            open = false;
            continue;
        }
        // A list item stands alone, and so does a line after one that ended a sentence, a colon or a URL; any other
        // line is the one before wrapping.
        const item = /^(\d+[.)]|[-•*])\s+/.test(line);
        if (open && !item) units[units.length - 1] += ` ${line}`;
        else units.push(item ? line.replace(/^(\d+[.)]|[-•*])\s+/, '') : line);
        open = !/([.!?:]|https?:\/\/\S+)$/.test(line);
    }
    return units.flatMap((unit) => unit.split(/(?<=[.!?])\s+(?=[A-Z])/)).map((s) => s.trim()).filter(Boolean);
}

/** A sentence without the URLs the source link already carries; null when nothing is left without them ("Get your
 *  API key at: <url>" is the link's job, "Go to <url>" says nothing). */
function withoutUrls(sentence: string): string | null {
    URL_RE.lastIndex = 0;
    if (!URL_RE.test(sentence)) return sentence;
    URL_RE.lastIndex = 0;
    // Only a URL that points somewhere ("at: <url>", "(<url>)", "Go to <url>") goes; an example of a value's shape
    // ("e.g. https://acme.example.com", "Use https://gitlab.com for SaaS") stays.
    const pointed = sentence
        .replace(/\(\s*https?:\/\/(?!localhost|127\.0\.0\.1)[^\s)]+\s*\)/gi, '')
        .replace(/\b(at|from|here|via|see|visit|to)(\s*:?\s*)https?:\/\/(?!localhost|127\.0\.0\.1)[^\s)'"`]+/gi, '$1')
        .replace(/\(\s*\)/g, '');
    if (pointed === sentence) return sentence;
    const s = pointed.replace(/\s*\b(at|here|from|in)?\s*:?\s*\.?$/i, '').trim();
    if (words(s).length <= 2) return null;
    if (/^(get|find|obtain|grab)\b/i.test(s) && words(s).length <= 6) return null;
    if (/\b(to|at|via)$/i.test(s)) return null;
    return s;
}

const sentence = (s: string) => (/[.!?]$/.test(s) ? s : `${s}.`);

/** The steps in a description: the sentences that tell you what to do, with the URLs the source link already carries
 *  taken out, and nothing about how the credential works inside. */
export function stepsFromDescription(description: string | null | undefined): string | null {
    if (!description) return null;
    const kept: string[] = [];
    for (const raw of sentencesOf(description)) {
        if (SELF_DESCRIPTION.test(raw)) continue;
        const s = withoutUrls(raw);
        if (!s || !STEP_START.test(s) || s.endsWith(':')) continue;
        kept.push(sentence(cleanMarkup(s)));
    }
    return kept.length ? kept.join(' ') : null;
}

/** Authored instructions are for people already; only their URLs (the source link's job) come out. */
function cleanInstructions(text: string): string | null {
    const kept = sentencesOf(text)
        .map(withoutUrls)
        .filter((s): s is string => !!s && !s.endsWith(':'))
        .map((s) => sentence(cleanMarkup(s)));
    return kept.length ? kept.join(' ') : null;
}

export function howToGet(method: CopyMethod, app?: string): string | null {
    if (method.kind !== 'api_key') return null;
    const steps = method.instructions?.trim() ? cleanInstructions(method.instructions) : stepsFromDescription(method.description);
    return steps && app ? asNamed(steps, app) : steps;
}

/** A schema's "BlueSky" written the way the catalog writes the app ("Bluesky"). */
export function asNamed(text: string, app: string): string {
    const escaped = app.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Never inside a host or an address ("acme.fellow.app", "Apollo.io").
    return text.replace(new RegExp(`(?<![./@-])\\b${escaped}\\b(?![./@:+-][\\w/])`, 'gi'), app);
}

export function sourceLink(method: CopyMethod): SourceLink | null {
    // A link the steps pointed at ("Create a script app at: <url>") is the source when the schema names none, since
    // the steps lose it.
    const pointed = (text?: string | null) => {
        const url = text?.match(POINTED_URL)?.slice(1).find(Boolean);
        return url && /^https?:\/\/[^/]+\.[a-z]{2,}/i.test(url) ? url : undefined;
    };
    const href = method.credentialUrl || method.fields?.find((f) => f.helpUrl)?.helpUrl || pointed(method.instructions) || pointed(method.description);
    if (!href) return null;
    try {
        const url = new URL(href);
        if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
        return { href, host: url.hostname.replace(/^www\./, '') };
    } catch {
        return null;
    }
}

export function methodCopy(method: CopyMethod, app: string, provider = app): MethodCopy {
    return {
        name: methodName(method, app, provider),
        line: methodLine(method, app, provider),
        howTo: howToGet(method, app),
        source: method.kind === 'api_key' ? sourceLink(method) : null,
    };
}

// ── Fields ───────────────────────────────────────────────────────────────────────────────────────────────────────────

const TRANSPORT = /^(passed|sent|used) (as|in|raw)\b/i;
// The same said mid-sentence ("; used as the HTTP Basic password", "to send as Authorization: Bearer <token>",
// "(Bearer token)").
const TRANSPORT_CLAUSE =
    /\s*[;,—–]\s*(?:(?:is|are)\s+)?(?:passed|sent|used)\s+(?:as|in)\b[^.;)]*|\s+to\s+(?:send|pass)(?:\s+it)?\s+as\b[^.;)]*|\s*\(\s*(?:(?:passed|sent|used)\s+(?:as|in)\b[^)]*|bearer(?:\s+token)?)\s*\)/gi;

/** A field's help without what the form already says: its label again ("Your Apollo.io API Key" under "API key"), its
 *  placeholder again ("e.g., user.bsky.social"), or the steps shown above it (`context`). "Your Notion Internal
 *  Integration Token (starts with 'ntn_' or 'secret_')" keeps "Starts with ntn_ or secret_.". */
export function fieldHelp(field: CopyField, app: string, context?: string | null): string | null {
    // How the value travels ("Passed as a Bearer token.", "Sent as the X-Api-Key header.") is NoClick's business.
    const text = sentencesOf((field.description ?? '').replace(TRANSPORT_CLAUSE, ''))
        .filter((s) => !TRANSPORT.test(s))
        .map((s) => withoutUrls(s) ?? '')
        .filter(Boolean)
        .join(' ')
        .replace(/\s*\(\s*e\.g\.,?\s*([^)]*)\)/gi, (whole, example: string) =>
            example.trim().toLowerCase() === field.placeholder?.trim().toLowerCase() ? '' : whole
        )
        .trim();
    if (!text) return null;
    // "Apollo.io" is the app by its domain.
    const plain = (s: string) => s.toLowerCase().replace(/\b([a-z0-9-]+)\.(io|com|ai|so|app|co|dev|net|org)\b/g, '$1').replace(/[^a-z0-9 ]/g, ' ');
    const known = new Set([...words(plain(field.label)), ...words(plain(app)), compact(app), ...words(plain(context ?? ''))]);
    const adds = (s: string) => words(plain(s)).some((w) => !STOP_WORDS.has(w) && !known.has(w));
    if (!adds(text)) return null;
    if (adds(text.replace(/\([^)]*\)/g, ' '))) return asNamed(cleanMarkup(text), app);
    // Only the brackets say something new.
    const inner = [...text.matchAll(/\(([^)]*)\)/g)].map((m) => m[1].trim()).filter((s) => s && !isAcronym(s) && adds(s));
    if (!inner.length) return null;
    const note = cleanMarkup(inner.join('; ').replace(/'/g, ''));
    return `${note.charAt(0).toUpperCase()}${note.slice(1)}${/[.!?]$/.test(note) ? '' : '.'}`;
}

/** What a required field left empty says under itself: "Enter the app password." */
export function missingFieldMessage(field: CopyField): string {
    return `Enter the ${lowerFirst(fieldLabel(field))}.`;
}

/** A field's label in sentence case, without an "(Optional)" the form marks on its own. */
export function fieldLabel(field: CopyField): string {
    return sentenceCase(field.label.replace(/\s*\(optional\)\s*/i, ' ').trim());
}
