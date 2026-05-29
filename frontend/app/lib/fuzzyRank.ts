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
