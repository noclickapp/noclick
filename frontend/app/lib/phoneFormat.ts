// Phone numbers travel as E.164 and are shown grouped for people.

/** '+14242421064' → '+1 424 242 1064' for display; the wire keeps E.164.
 *  Ten national digits read as 3-3-4; anything else groups by threes from the right. */
export function formatPhoneForDisplay(e164: string): string {
    const digits = e164.replace(/^\+/, '');
    if (digits.length <= 4) return e164;
    const country = digits.length > 10 ? digits.slice(0, digits.length - 10) : digits.slice(0, 1);
    const rest = digits.slice(country.length);
    const groups = rest.length === 10
        ? [rest.slice(0, 3), rest.slice(3, 6), rest.slice(6)]
        : rest.match(/.{1,3}(?=(.{3})*$)/g) ?? [rest];
    return `+${country} ${groups.join(' ')}`;
}

const KEYPAD: Record<string, string> = {
    A: '2', B: '2', C: '2', D: '3', E: '3', F: '3', G: '4', H: '4', I: '4', J: '5', K: '5', L: '5',
    M: '6', N: '6', O: '6', P: '7', Q: '7', R: '7', S: '7', T: '8', U: '8', V: '8', W: '9', X: '9', Y: '9', Z: '9',
};

/** Where a search pattern (digits, keypad letters, * wildcards) sits inside a
 *  number's national digits — [start, end) — or null. Lets the result list
 *  show WHY a number matched. */
export function patternSpan(e164: string, pattern: string): [number, number] | null {
    const cleaned = pattern.toUpperCase().replace(/[^0-9A-Z*]/g, '');
    if (!cleaned) return null;
    const digits = e164.replace(/^\+/, '');
    const national = digits.length > 10 ? digits.slice(digits.length - 10) : digits;
    const regex = new RegExp(cleaned.split('').map((c) => (c === '*' ? '\\d' : KEYPAD[c] ?? c)).join(''));
    const hit = regex.exec(national);
    if (!hit) return null;
    const offset = digits.length - national.length;
    return [offset + hit.index, offset + hit.index + hit[0].length];
}

export const NUMBER_CELLS = 10;

export type PatternMode = 'positions' | 'anywhere';

/** What the number picker asks the provider for.
 *  - `positions`: the ten cells are the number's positions; blank cells match
 *    anything. Only the area code filled is an area-code search; any other
 *    shape is a positional pattern (ten characters anchor it).
 *  - `anywhere`: the filled cells, read left to right, must appear somewhere
 *    in the number — the provider's unanchored contains search. */
export function searchQueryFromCells(cells: string[], mode: PatternMode = 'positions'): { area_code: string | null; contains: string | null } {
    const pattern = Array.from({ length: NUMBER_CELLS }, (_, i) => (cells[i] || '*').toUpperCase());
    if (pattern.every((c) => c === '*')) return { area_code: null, contains: null };
    if (mode === 'anywhere') {
        const run = pattern.join('').replace(/^\*+|\*+$/g, '');
        return { area_code: null, contains: run };
    }
    const area = pattern.slice(0, 3);
    const rest = pattern.slice(3);
    if (area.every((c) => c !== '*' && /\d/.test(c)) && rest.every((c) => c === '*')) {
        return { area_code: area.join(''), contains: null };
    }
    return { area_code: null, contains: pattern.join('') };
}
