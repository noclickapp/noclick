// How a link in a reply reads. A model often pastes a raw URL (a capability link can run past a hundred characters),
// which is unreadable and widens a phone's screen. So a link whose words are its own address reads short (its site and
// a trimmed path), one of NoClick's own links for a person reads as what it does ("Purchase link"), and a link the
// model gave words keeps them. The full URL stays the link's target either way. A link one of the reply's asks draws as
// a row under it shows there alone (`withoutAskLinks`).
import type { TurnAsk } from './turnAsks';

/** NoClick's own pages a person is sent to, by path, and what each link does. First match wins. */
const CAPABILITY_LINKS: [RegExp, string][] = [
    [/^\/credential\/purchase\//, 'Purchase link'],
    [/^\/(pay|upi)\//, 'Payment link'],
    [/^\/upgrade\/?$/, 'Upgrade'],
    [/^\/credential\/provide\//, 'Connect link'],
    [/^\/connect\//, 'Connect link'],
    [/^\/(approve|credential\/approval)\//, 'Approve'],
    [/^\/credential\/permissions\//, 'Permissions'],
    [/^\/(b|h)\//, 'Request link'],
    [/^\/secrets\//, 'Add secrets'],
    [/^\/sign\//, 'Signing link'],
    [/^\/live\//, 'Live view'],
    [/^\/a\//, 'Chat link'],
    [/^\/r\//, 'Run link'],
    [/^\/c\//, 'Card'],
    [/^\/claim\//, 'Claim link'],
    [/^\/(invite|join|i|organization\/invite)\//, 'Invite link'],
];

/** The hosts NoClick's pages live on, besides the one this page was served from. */
const NOCLICK_HOSTS = /^(?:www\.)?noclick\.(?:com|app)$/;

/** A path segment longer than this reads as its first four and last three characters. */
const LONG_SEGMENT = 16;
/** A short address longer than this keeps its site and its last segment only. */
const LONG_ADDRESS = 48;

export type LinkDisplay =
    /** The link's own words, as written. */
    | { kind: 'text' }
    /** The address, shortened. */
    | { kind: 'short'; text: string }
    /** One of NoClick's links for a person, named for what it does. */
    | { kind: 'capability'; label: string };

function parse(href: string): URL | null {
    try {
        const url = new URL(href);
        return url.protocol === 'http:' || url.protocol === 'https:' ? url : null;
    } catch {
        return null;
    }
}

function decode(part: string): string {
    try {
        return decodeURIComponent(part);
    } catch {
        return part;
    }
}

/** An address as a person compares it: no scheme, no `www.`, no trailing slash, decoded. */
function bare(address: string): string {
    return decode(address.trim())
        .replace(/^https?:\/\//i, '')
        .replace(/^www\./i, '')
        .replace(/\/+$/, '')
        .toLowerCase();
}

/** Whether a link's words are an address rather than words someone chose. */
function wordsAreAnAddress(words: string, url: URL): boolean {
    const w = words.trim();
    if (!w || /\s/.test(w)) return false;
    return /^(https?:\/\/|www\.)/i.test(w) || bare(w) === bare(url.href);
}

/** The address shortened: its site (no `www.`) and its path, each long segment trimmed to `ff9f…3d9`. */
export function shortAddress(url: URL): string {
    const host = url.hostname.replace(/^www\./, '');
    const segments = url.pathname
        .split('/')
        .filter(Boolean)
        .map(decode)
        .map((s) => (s.length > LONG_SEGMENT ? `${s.slice(0, 4)}…${s.slice(-3)}` : s));
    const more = url.search || url.hash ? '…' : '';
    const full = [host, ...segments].join('/') + more;
    if (full.length <= LONG_ADDRESS || segments.length < 2) return full;
    return `${host}/…/${segments[segments.length - 1]}${more}`;
}

function isNoClick(url: URL, here: string | undefined): boolean {
    return NOCLICK_HOSTS.test(url.hostname) || (!!here && url.host === here);
}

/** How a reply's link to `href` whose words are `words` reads. `here` is the host this page was served from. */
export function linkDisplay(href: string | undefined, words: string, here?: string): LinkDisplay {
    const url = href ? parse(href) : null;
    if (!url || !wordsAreAnAddress(words, url)) return { kind: 'text' };
    if (isNoClick(url, here)) {
        const capability = CAPABILITY_LINKS.find(([path]) => path.test(url.pathname));
        if (capability) return { kind: 'capability', label: capability[1] };
    }
    return { kind: 'short', text: shortAddress(url) };
}

/** A link in a reply's Markdown, after the spaces before it: with words (`[words](url)`), in angle brackets, or bare. */
const LINK = /([ \t]*)(?:\[([^\]\n]*)\]\(<?(https?:\/\/[^\s)>]+)>?\)|<(https?:\/\/[^\s>]+)>|(https?:\/\/[^\s<>()[\]]+))/g;
/** What ends a sentence after a bare address, never part of it (as Markdown reads one). */
const AFTER = /[.,;:!?'"*_~]+$/;

/** A reply's words with each link one of its asks draws as a row under it (an account's connect link, a payment's, an
 *  approval's page) left to the row, so each ask reads once. Words the model gave such a link stay, as plain words:
 *  they're part of its sentence. An address goes: as plain text it's an unreadable token saying nothing the row
 *  doesn't, and it nearly always ends its sentence ("Connect Gmail here: …"); a line that was only the link goes with
 *  it. Every other link stays as written. */
export function withoutAskLinks(text: string, asks: readonly TurnAsk[]): string {
    // Where a link leads, by its path (its token's there), whatever host it's written with.
    const pageOf = (href: string) => parse(href.startsWith('/') ? `https://noclick.com${href}` : href)?.pathname.replace(/\/+$/, '') || null;
    const drawn = new Set(asks.flatMap((a) => (a.kind === 'secret' ? [] : [pageOf(a.kind === 'approval' ? `/approve/${a.approvalId}` : a.url)])).filter(Boolean));
    if (!drawn.size) return text;
    const strip = (line: string, keepWords: boolean) =>
        line.replace(LINK, (match: string, lead: string, words?: string, linked?: string, angled?: string, bare?: string) => {
            const href = linked ?? angled ?? bare!.replace(AFTER, '');
            if (!drawn.has(pageOf(href))) return match;
            const tail = bare?.slice(href.length) ?? '';
            return keepWords && words !== undefined && !wordsAreAnAddress(words, parse(href)!) ? lead + words + tail : tail;
        });
    return text
        .split('\n')
        .flatMap((line) => {
            const kept = strip(line, true);
            if (kept === line) return [line];
            // A colon that led to the address reads as the sentence's end ("here: ." reads "here.").
            return /[\p{L}\p{N}]/u.test(strip(line, false)) ? [kept.replace(/:([.!?])/g, '$1')] : [];
        })
        .join('\n');
}
