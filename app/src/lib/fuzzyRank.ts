// Lightweight fuzzy match/ranking used by the command palette (and reusable by
// any search-as-you-type list). Returns a score where LOWER is a better match,
// or null when there's no match at all. Ranking: exact > prefix > substring
// (earlier position wins) > subsequence. No dependency, deliberately tiny.

export function scoreMatch(text: string, query: string): number | null {
    const t = text.toLowerCase();
    const q = query.toLowerCase().trim();
    if (!q) return 0;
    if (t === q) return 0;
    if (t.startsWith(q)) return 1;
    const idx = t.indexOf(q);
    if (idx >= 0) return 2 + idx / 1000; // contiguous match, earlier = slightly better
    // Subsequence fallback: every query char appears in order (fuzzy).
    let ti = 0;
    for (let qi = 0; qi < q.length; qi++) {
        ti = t.indexOf(q[qi], ti);
        if (ti === -1) return null;
        ti += 1;
    }
    return 3;
}

// Score an item against several haystacks (e.g. label + keywords), keeping the
// best (lowest) score across them. Returns null if none match.
export function scoreFields(
    query: string,
    fields: (string | undefined | null)[]
): number | null {
    let best: number | null = null;
    for (const f of fields) {
        if (!f) continue;
        const s = scoreMatch(f, query);
        if (s === null) continue;
        if (best === null || s < best) best = s;
    }
    return best;
}

/** Something a search finds by name: its name first, then the other words people use for it, where it lives, and a
 *  line about it. */
export interface Named {
    label: string;
    /** Other words for it, space-separated. A query that is one of them (or a run of them) ranks it nearly as if it
     *  were its name, so "dns" finds Domains first. */
    keywords?: string;
    /** Where it lives ("Resources"), matched alongside other words: "resources domains". */
    context?: string;
    /** A sentence about it, matched last and on whole words. */
    about?: string;
}

// Lower ranks first. Words count from their starts: "keys" finds "API keys", "eys" doesn't.
const EXACT = 0;
const SYNONYM = 0.5;
const PREFIX = 1;
const WORD = 1.5;
const ALL_IN_NAME = 1.6;
const ALL_WORDS = 2.2;
const KEYWORD_START = 2.5;
const CONTAINS = 3;
const ABOUT = 3.5;
const SCATTERED = 4;
const NO_MATCH = 5;

const BOUNDARY = /[\s\-_/·,:;()&.@+'’"]/;

const normalize = (s: string) => s.toLowerCase().replace(/\s+/g, ' ').trim();

/** Where `q` starts a word of `text`, or -1. */
function wordStart(text: string, q: string): number {
    for (let i = text.indexOf(q); i >= 0; i = text.indexOf(q, i + 1)) {
        if (i === 0 || BOUNDARY.test(text[i - 1])) return i;
    }
    return -1;
}

function nameTier(name: string, q: string, tokens: string[]): number {
    if (name === q) return EXACT;
    if (name.startsWith(q)) return PREFIX;
    if (wordStart(name, q) >= 0) return WORD;
    if (tokens.length > 1 && tokens.every((t) => wordStart(name, t) >= 0)) return ALL_IN_NAME;
    const at = name.indexOf(q);
    if (at >= 0) return CONTAINS + at / 1000;
    return scoreMatch(name, q) === null ? NO_MATCH : SCATTERED;
}

/**
 * How well `query` finds `item`, lower being better, or null when it doesn't. By its name: exact, then a prefix, then
 * the start of one of its words, then all the query's words; by a keyword the query is, nearly as well as by name; by
 * all the query's words across name, place and keywords; by a keyword it begins; by its name containing the query; by
 * a word of its about line; by the query's letters in order. Among equals, the one whose name matches better leads.
 * A leading "go to" is ignored, as the palette's rows once read.
 */
export function scoreNamed(query: string, item: Named): number | null {
    const q = normalize(query).replace(/^go ?to /, '');
    if (!q) return 0;
    const tokens = q.split(' ');
    const name = normalize(item.label);
    const keywords = item.keywords ? normalize(item.keywords) : '';
    const byName = nameTier(name, q, tokens);
    let tier = byName;
    if (keywords && tier > SYNONYM) {
        // One letter is no word anyone means.
        if (q.length > 1 && ` ${keywords} `.includes(` ${q} `)) tier = SYNONYM;
        else if (tier > KEYWORD_START && wordStart(keywords, q) >= 0) tier = KEYWORD_START;
    }
    if (tier > ALL_WORDS && tokens.length > 1) {
        const context = item.context ? normalize(item.context) : '';
        let keywordOnly = 0;
        const all = tokens.every((t) => {
            if (wordStart(name, t) >= 0 || (context && wordStart(context, t) >= 0)) return true;
            if (!keywords || wordStart(keywords, t) < 0) return false;
            keywordOnly += 1;
            return true;
        });
        // A word only a keyword holds is weaker than one in its name or place.
        if (all) tier = Math.min(tier, ALL_WORDS + (0.1 * keywordOnly) / tokens.length);
    }
    if (tier > ABOUT && item.about && q.length >= 3 && wordStart(normalize(item.about), q) >= 0) tier = ABOUT;
    if (tier >= NO_MATCH) return null;
    return tier + byName / 100;
}
