/**
 * Boolean config fields render as a Yes/No select. As a bare text input they
 * invited free text ("no", "hapana") that the runtime parse rejected with
 * "Input should be a valid boolean" (2026-09-10).
 */
import { describe, expect, it } from 'vitest';
import { booleanSelectValue, isBooleanSchema } from '~/utils/schemaFieldExtractor';

describe('isBooleanSchema', () => {
    it('recognises plain, nullable and Optional[bool] shapes', () => {
        expect(isBooleanSchema({ type: 'boolean', default: false })).toBe(true);
        expect(isBooleanSchema({ type: ['boolean', 'null'] })).toBe(true);
        expect(isBooleanSchema({ anyOf: [{ type: 'boolean' }, { type: 'null' }] })).toBe(true);
    });

    it('leaves string-capable and non-boolean fields to the text input', () => {
        expect(isBooleanSchema({ type: 'string', enum: ['true', 'false'] })).toBe(false);
        expect(isBooleanSchema({ anyOf: [{ type: 'boolean' }, { type: 'string' }] })).toBe(false);
        expect(isBooleanSchema({ type: 'number' })).toBe(false);
        expect(isBooleanSchema(undefined)).toBe(false);
    });
});

describe('booleanSelectValue', () => {
    it('maps stored booleans and their string forms; unset is empty', () => {
        expect(booleanSelectValue(true)).toBe('true');
        expect(booleanSelectValue('true')).toBe('true');
        expect(booleanSelectValue(false)).toBe('false');
        expect(booleanSelectValue('false')).toBe('false');
        expect(booleanSelectValue(undefined)).toBe('');
        expect(booleanSelectValue('')).toBe('');
    });
});
