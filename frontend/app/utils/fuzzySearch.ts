// General-purpose, weighted fuzzy search scorer. Built for the operation/action
// picker (OperationPicker) so typing "msg send", "send message", or "snmsg"
// all surface "Send Message" — the old picker did a single literal substring
// match on the label, which failed on word reordering, abbreviations, typos,
// and never looked at the operation value/category/description. Kept generic
// (fields + weights in, relevance score out) so other pickers can reuse it.
//
// Each query token is also expanded through a curated synonym map
// (operationSynonyms.ts) so an action surfaces even when its label uses a
// different word than the user typed ("get rows" → "Read ... Data", "list
// records" → "Get Records"). Synonym hits score below the literal token (see
// SYNONYM_PENALTY) so exact-word matches always rank first.

import { expandQueryTerm } from './operationSynonyms';

export interface SearchField {
    /** Lowercased haystack text for this field. */
    text: string;
    /** Relative importance — a hit on a heavier field outranks a lighter one. */
    weight: number;
    /** Allow subsequence (fuzzy) matching on this field. Enable for short,
     *  identity-like fields (label, operation value); leave off for long prose
     *  (descriptions) where scattered-character matches would be noise. */
    fuzzy?: boolean;
}

const WORD_BOUNDARY = /[^a-z0-9]/;

// Synonym matches are real but weaker evidence than the user's literal word, so
// they're discounted. A clean synonym (word-boundary, ~0.75) still outscores a
// stretchy subsequence match of the literal, which is the intended ordering.
const SYNONYM_PENALTY = 0.8;

export function tokenizeQuery(query: string): string[] {
    return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/** Greedy in-order character match. Rewards consecutive runs and word-start
 *  hits; rejects when the term doesn't fully appear or its matched span is so
 *  spread out it's almost certainly coincidental. Returns ~0.2–0.45, or null. */
function subsequenceScore(text: string, term: string): number | null {
    let ti = 0;
    let run = 0;
    let raw = 0;
    let first = -1;
    let prev = -2;
    for (let i = 0; i < text.length && ti < term.length; i++) {
        if (text[i] !== term[ti]) continue;
        if (first < 0) first = i;
        let bonus = 1;
        if (i === prev + 1) bonus += ++run;
        else run = 0;
        if (i === 0 || WORD_BOUNDARY.test(text[i - 1])) bonus += 2;
        raw += bonus;
        prev = i;
        ti++;
    }
    if (ti < term.length) return null;
    // Reject matches whose characters are scattered far apart (coincidental).
    if (prev - first + 1 > term.length * 8) return null;
    const normalized = raw / (term.length * 4);
    return 0.2 + Math.min(normalized, 1) * 0.25;
}

/** Score how well a single (whitespace-free) term matches `text`, 0..1, or null
 *  if there's no match. Tiered: exact > prefix > word-boundary > substring >
 *  subsequence (only when `fuzzy`). */
export function matchTerm(
    text: string,
    term: string,
    fuzzy: boolean
): number | null {
    if (!text || !term) return null;
    if (text === term) return 1;
    if (text.startsWith(term)) return 0.9;
    const idx = text.indexOf(term);
    if (idx >= 0) {
        const atBoundary = idx === 0 || WORD_BOUNDARY.test(text[idx - 1]);
        // Word-boundary substrings beat mid-word ones; earlier beats later.
        return atBoundary ? 0.75 : 0.55 - Math.min(idx, 20) / 100;
    }
    return fuzzy ? subsequenceScore(text, term) : null;
}

/** Score a query against a set of weighted fields. Every query token must match
 *  at least one field — by the literal token OR one of its synonyms (AND
 *  semantics across tokens) — otherwise the option doesn't match and null is
 *  returned. Each token contributes its best weighted field score, so token
 *  order is irrelevant. A multi-word query that appears contiguously in the
 *  heaviest field gets a small bonus, keeping exact phrases on top. */
export function scoreFields(
    fields: SearchField[],
    query: string
): number | null {
    const terms = tokenizeQuery(query);
    if (terms.length === 0) return 0;
    let total = 0;
    for (const term of terms) {
        let matched = false;
        let best = 0;
        // The literal term first (full weight, honoring each field's fuzzy
        // flag), then synonyms (discounted, exact/substring only — never
        // subsequence — so an expanded word can't match on scattered chars).
        const variants = expandQueryTerm(term);
        for (let v = 0; v < variants.length; v++) {
            const variant = variants[v];
            const isLiteral = v === 0;
            const penalty = isLiteral ? 1 : SYNONYM_PENALTY;
            for (const f of fields) {
                const m = matchTerm(
                    f.text,
                    variant,
                    isLiteral ? (f.fuzzy ?? false) : false
                );
                if (m === null) continue;
                matched = true;
                const weighted = m * f.weight * penalty;
                if (weighted > best) best = weighted;
            }
        }
        if (!matched) return null;
        total += best;
    }
    if (terms.length > 1) {
        // Reward a contiguous match of the whole query in any field, scaled by
        // that field's weight — so an exact phrase in the label (weight 1) beats
        // the same phrase only appearing in authored keywords (weight 0.6), and
        // both keep exact phrases above scattered token matches.
        const phrase = terms.join(' ');
        let bonus = 0;
        for (const f of fields) {
            if (f.text.includes(phrase))
                bonus = Math.max(bonus, 0.5 * f.weight);
        }
        total += bonus;
    }
    return total;
}

/** Filter + rank a list of items against a query using the token-based scorer
 *  above. `getFields` maps an item to its weighted search fields (text MUST be
 *  lowercased). Items that don't match every token are dropped; the rest are
 *  returned best-first. An empty query returns the list unchanged (original
 *  order). This is the one-liner every search-as-you-type list should use so
 *  multi-word, reordered, and abbreviated queries work identically everywhere. */
export function fuzzyFilter<T>(
    items: T[],
    query: string,
    getFields: (item: T) => SearchField[]
): T[] {
    if (!query.trim()) return items;
    const scored: { item: T; score: number }[] = [];
    for (const item of items) {
        const score = scoreFields(getFields(item), query);
        if (score !== null) scored.push({ item, score });
    }
    // Stable within equal scores: Array.prototype.sort is stable, so items keep
    // their original relative order when scores tie.
    scored.sort((a, b) => b.score - a.score);
    return scored.map((s) => s.item);
}
