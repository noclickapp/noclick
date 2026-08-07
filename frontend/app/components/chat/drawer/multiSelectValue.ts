// Encoding helpers for multi-select <ask> answers (ask multiple="true") in the
// builder input drawer. While editing, a multi-select answer lives in the wizard's
// values map as 'multi:' + JSON ({selected, other}) so step navigation round-trips
// losslessly; on submit it is flattened to a comma-joined string for the brain.

export const MULTI_PREFIX = 'multi:';

export interface MultiValue {
    /** Chosen option ids, in click order. */
    selected: string[];
    /** "Other" free text — null when the Other row isn't checked. */
    other: string | null;
}

export function parseMultiValue(value: string | undefined): MultiValue {
    if (value?.startsWith(MULTI_PREFIX)) {
        try {
            const parsed = JSON.parse(value.slice(MULTI_PREFIX.length));
            if (parsed && Array.isArray(parsed.selected)) {
                return {
                    selected: parsed.selected.filter((s: unknown): s is string => typeof s === 'string'),
                    other: typeof parsed.other === 'string' ? parsed.other : null,
                };
            }
        } catch { /* malformed — treat as empty */ }
    }
    return { selected: [], other: null };
}

export function encodeMultiValue(mv: MultiValue): string {
    return MULTI_PREFIX + JSON.stringify(mv);
}

/** The submitted answer: chosen options plus non-empty Other text, comma-joined. */
export function flattenMultiValue(value: string): string {
    const { selected, other } = parseMultiValue(value);
    const parts = [...selected];
    const otherText = (other ?? '').trim();
    if (otherText) parts.push(otherText);
    return parts.join(', ');
}
