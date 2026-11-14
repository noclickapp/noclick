// How a link in a reply reads. A model often pastes a raw URL (a capability link can run past a hundred characters),
// which is unreadable and widens a phone's screen. So a link whose words are its own address reads short (its site and
// a trimmed path), one of NoClick's own links for a person reads as what it does ("Purchase link"), and a link the
// model gave words keeps them. The full URL stays the link's target either way.

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
const NOCLICK_HOSTS = /^(?:www\.|staging\.)?noclick\.(?:com|app)$/;

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
