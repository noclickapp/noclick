import { describe, expect, it } from 'vitest';
import { compileConfigSchema, evaluateShowIf, isValidTimeZone, judgeConfigForm } from './configForm';
import { EMPTY_STEP_REFERENCE_MESSAGE } from './expressionSyntax';
import { schemaInfoOf } from './stepSchema';
import { describeRequireOneOfGroup, evaluateRequireOneOf, hasDefaultValue, isFieldEmpty, isFieldRequired } from './stepFields';

const SEND = {
    properties: {
        operation: { const: 'send', 'ui:hidden': true },
        channel: { type: 'string', title: 'Channel', minLength: 1 },
        count: { type: 'integer', default: 1 },
        recipients: { type: 'array', items: { type: 'string' }, 'ui:widget': 'list' },
        mode: { type: 'string', enum: ['plain', 'advanced'] },
        advanced_only: { type: 'string', title: 'Advanced setting', 'ui:show-if': { field: 'mode', contains: 'advanced' } },
        zone: { type: 'string', format: 'timezone' },
        model: { type: 'string', enum: ['a', 'b'], 'x-enum-allow-custom': true },
        text: { type: 'string', title: 'Text' },
        blocks: { type: 'string', title: 'Blocks' },
    },
    required: ['channel', 'advanced_only'],
    'x-require-one-of': [[['text'], ['blocks']]],
};
const STEP = {
    properties: { config: { $ref: '#/$defs/C' } },
    $defs: { C: { oneOf: [{ $ref: '#/$defs/Send' }, { $ref: '#/$defs/Other' }] }, Send: SEND, Other: { properties: { operation: { const: 'other' } } } },
};
const info = schemaInfoOf(STEP);
const judge = (config: Record<string, unknown>, operation: string | undefined) => judgeConfigForm(info, 'step', config, operation);

describe('judgeConfigForm', () => {
    it('has nothing to judge without a schema, and asks for an action first', () => {
        expect(judgeConfigForm(null, 'step', {}, undefined)).toEqual({ valid: false, errors: [{ message: 'No schema found for this node type', type: 'general' }] });
        expect(judge({}, undefined)).toEqual({ valid: false, errors: [{ message: 'Choose an action', type: 'general' }] });
    });

    it('names each missing or empty required field once, and the either-or group', () => {
        expect(judge({ channel: '' }, 'send').errors).toEqual([
            { message: 'is required', fieldKey: 'channel', fieldLabel: 'Channel', type: 'field' },
            { message: 'Provide Text or Blocks', fieldKey: 'text', fieldLabel: 'Text', type: 'field' },
        ]);
    });

    it('judges a field shown only when its condition holds', () => {
        expect(judge({ channel: 'c', text: 't', mode: 'advanced' }, 'send').errors).toEqual([
            { message: 'is required', fieldKey: 'advanced_only', fieldLabel: 'Advanced setting', type: 'field' },
        ]);
        expect(judge({ channel: 'c', text: 't', mode: 'plain' }, 'send')).toEqual({ valid: true, errors: [] });
    });

    it('lets a reference, a list written as text, a default and a custom value through', () => {
        expect(
            judge({ channel: "{{ $('a').channel }}", blocks: 'b', recipients: 'ada@example.test, bo@example.test', count: null, model: 'c', zone: 'Asia/Kolkata' }, 'send'),
        ).toEqual({ valid: true, errors: [] });
    });

    it('says what a wrong value must be', () => {
        expect(judge({ channel: 'c', text: 't', mode: 'other', zone: 'Mars/Base' }, 'send').errors).toEqual([
            { message: 'must be one of: plain, advanced', fieldKey: 'mode', fieldLabel: 'mode', type: 'field' },
            { message: 'must be a valid timezone', fieldKey: 'zone', fieldLabel: 'zone', type: 'field' },
        ]);
    });

    it('names a field holding a step reference with no step picked, wherever in it', () => {
        expect(judge({ channel: 'c', text: "Reply to {{ $('') }} soon", recipients: ['{{ $("").to }}'] }, 'send').errors).toEqual([
            { message: EMPTY_STEP_REFERENCE_MESSAGE, fieldKey: 'recipients', fieldLabel: 'recipients', type: 'field' },
            { message: EMPTY_STEP_REFERENCE_MESSAGE, fieldKey: 'text', fieldLabel: 'Text', type: 'field' },
        ]);
        expect(judge({ channel: 'c', text: "Reply to {{ $('trigger').from }} {{ $json }}" }, 'send')).toEqual({ valid: true, errors: [] });
    });

    it("leaves an API agent's instructions alone: a run hands them over as written", () => {
        const agent = schemaInfoOf({ properties: { system_prompt: { type: 'string', title: 'System Prompt' }, message: { type: 'string', title: 'Message' } } });
        const quoting = { system_prompt: "Explain {{ $('') }}.", message: "Go {{ $('') }}" };
        expect(judgeConfigForm(agent, 'agent', quoting, undefined).errors.map((e) => e.fieldKey)).toEqual(['system_prompt', 'message']);
        expect(judgeConfigForm(agent, 'agent', { ...quoting, message_per_turn: true }, undefined).errors.map((e) => e.fieldKey)).toEqual(['message']);
    });

    it("holds TikTok's disclosure rule for a direct post", () => {
        const tiktok = schemaInfoOf({ properties: { disclose_commercial_content: { type: 'string' } } });
        expect(judgeConfigForm(tiktok, 'automation-tiktok', { disclose_commercial_content: 'true' }, 'direct_post_video').errors).toEqual([
            { message: 'Select your own brand, a paid partnership, or both before running.', type: 'general' },
        ]);
    });
});

describe('the field rules', () => {
    it('reads a show-if condition', () => {
        expect(evaluateShowIf({ field: 'm', containsAny: ['x', 'Y'] }, { m: 'a y' })).toBe(true);
        expect(evaluateShowIf({ field: 'm', containsAll: ['a', 'b'] }, { m: 'a' })).toBe(false);
        expect(evaluateShowIf({ field: 'm', contains: 'a', notContains: 'b' }, { m: 'ab' })).toBe(false);
        expect(evaluateShowIf({ anyOf: [{ field: 'm', contains: 'q' }, { field: 'n', contains: 'r' }] }, { n: 'r' })).toBe(true);
    });

    it('knows a time zone', () => {
        expect(isValidTimeZone('UTC')).toBe(true);
        expect(isValidTimeZone('Not/AZone')).toBe(false);
    });

    it('judges emptiness, defaults and what a person must fill', () => {
        expect([undefined, null, ' ', [], 0, false, 'x'].map(isFieldEmpty)).toEqual([true, true, true, true, false, false, false]);
        expect(hasDefaultValue({ anyOf: [{ type: 'string' }, { type: 'null' }] })).toBe(true);
        expect(isFieldRequired({ key: 'operation', required: true, prop: {} }, 'operation')).toBe(false);
        expect(isFieldRequired({ key: 'channel', required: true, prop: {} })).toBe(true);
    });

    it('finds the either-or groups no alternative satisfies', () => {
        const { unsatisfiedGroups, attentionKeys } = evaluateRequireOneOf([[['id'], ['lat', 'lng']]], { lat: 1, lng: '' });
        expect(unsatisfiedGroups).toEqual([[['id'], ['lat', 'lng']]]);
        expect([...attentionKeys]).toEqual(['id', 'lng']);
        expect(describeRequireOneOfGroup([['id'], ['lat', 'lng']], (k) => k.toUpperCase())).toBe('ID or LAT + LNG');
    });
});

describe('compileConfigSchema', () => {
    it('compiles a draft 2020-12 schema the form can judge with', () => {
        const validate = compileConfigSchema({ type: 'object', properties: { n: { type: 'number', exclusiveMinimum: 0 }, name: { type: 'string', pattern: "^\\w[\\w './()-]+$" } } });
        expect(validate({ n: 1, name: "Ada's repo (v2)" })).toBe(true);
        expect(validate({ n: 0 })).toBe(false);
    });

    it("refuses a pattern a u regex can't hold and a keyword in a form the dialect forbids", () => {
        expect(() => compileConfigSchema({ properties: { name: { type: 'string', pattern: "^[\\w\\']+$" } } })).toThrow(/Invalid escape/);
        expect(() => compileConfigSchema({ properties: { n: { type: 'number', minimum: 0, exclusiveMinimum: true } } })).toThrow(/exclusiveMinimum must be number/);
        expect(() => compileConfigSchema({ properties: { v: { type: 'any' } } })).toThrow(/schema is invalid/);
    });
});
