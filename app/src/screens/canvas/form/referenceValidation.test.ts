// Tests for reference validation, focused on the dual-mode contract: a `$()`/`$vars`
// accessor's property chain is JavaScript (evaluated server-side) so only its data
// SOURCE is validated — a JS property like `.length` must NOT be flagged invalid — while
// a legacy `{{node.field}}` ref still gets full data-path validation. Added for inline
// expressions (regression: `$('node').field.length` showed red despite a valid result).

import { describe, it, expect } from 'vitest';
import type { Node } from '@xyflow/react';
import { createValidator } from './ReferenceAutocompleteContext';

const nodes = [
    { id: 'sheets_s9209', type: 'automation-google-sheets', data: { output: { spreadsheet_id: 'abc123def456' } } },
] as unknown as Node[];

const vars = { threshold: 10 };

describe('createValidator — $() accessor leniency', () => {
    const validate = createValidator(nodes, undefined, vars);

    it('accepts a JS property on a valid node (the .length regression)', () => {
        expect(validate("$('sheets_s9209').spreadsheet_id.length").valid).toBe(true);
    });
    it('accepts a plain field accessor on a valid node', () => {
        expect(validate("$('sheets_s9209').spreadsheet_id").valid).toBe(true);
        expect(validate("$('sheets_s9209')").valid).toBe(true);
    });
    it('accepts an unknown field on a valid node (path is JS, preview is the signal)', () => {
        expect(validate("$('sheets_s9209').not_a_real_field").valid).toBe(true);
    });
    it('still rejects an accessor whose node does not exist', () => {
        const r = validate("$('ghost').spreadsheet_id.length");
        expect(r.valid).toBe(false);
        expect(r.error).toContain('ghost');
    });
    it('accepts a $vars accessor when variables exist, regardless of key', () => {
        expect(validate('$vars.threshold').valid).toBe(true);
        expect(validate('$vars.anything').valid).toBe(true);
    });
    it('rejects a $vars accessor when no variables are defined', () => {
        const noVars = createValidator(nodes, undefined, {});
        expect(noVars('$vars.threshold').valid).toBe(false);
    });
});
