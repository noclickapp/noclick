// Unit tests for the multi-select <ask> value encoding: the MULTI_PREFIX JSON
// round-trip the drawer edits through, and the comma-joined flattening that
// becomes the submitted answer the builder brain reads.

import { describe, expect, it } from 'vitest';
import { MULTI_PREFIX, encodeMultiValue, flattenMultiValue, parseMultiValue } from './multiSelectValue';

describe('parseMultiValue', () => {
    it('round-trips encode → parse', () => {
        const mv = { selected: ['A', 'B'], other: 'custom' };
        expect(parseMultiValue(encodeMultiValue(mv))).toEqual(mv);
    });

    it('returns empty state for undefined, non-multi, and malformed values', () => {
        expect(parseMultiValue(undefined)).toEqual({ selected: [], other: null });
        expect(parseMultiValue('plain answer')).toEqual({ selected: [], other: null });
        expect(parseMultiValue(`${MULTI_PREFIX}not-json`)).toEqual({ selected: [], other: null });
        expect(parseMultiValue(`${MULTI_PREFIX}{"selected":"nope"}`)).toEqual({ selected: [], other: null });
    });

    it('drops non-string entries and coerces a missing other to null', () => {
        expect(parseMultiValue(`${MULTI_PREFIX}{"selected":["A",1,null]}`)).toEqual({
            selected: ['A'],
            other: null,
        });
    });
});

describe('flattenMultiValue', () => {
    it('joins selected options with a comma', () => {
        expect(flattenMultiValue(encodeMultiValue({ selected: ['A', 'B'], other: null }))).toBe('A, B');
    });

    it('appends non-empty Other text and ignores a checked-but-empty Other', () => {
        expect(flattenMultiValue(encodeMultiValue({ selected: ['A'], other: ' custom ' }))).toBe('A, custom');
        expect(flattenMultiValue(encodeMultiValue({ selected: ['A'], other: '' }))).toBe('A');
        expect(flattenMultiValue(encodeMultiValue({ selected: [], other: null }))).toBe('');
    });
});
