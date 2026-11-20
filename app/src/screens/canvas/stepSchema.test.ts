import { describe, expect, it } from 'vitest';
import {
    booleanSelectValue,
    fieldsForOption,
    isBooleanSchema,
    isListSchema,
    listLabels,
    offersOperationChoice,
    operationsOf,
    optionLabelOf,
    requireOneOfGroupsOf,
    schemaInfoOf,
} from './stepSchema';

// A step with two operations, as the generator writes one: a discriminated union under `config`, each option a $def.
const SEND = {
    title: 'SendMessageConfig',
    properties: {
        operation: { const: 'send_message', 'ui:hidden': true },
        channel: { type: 'string', title: 'Channel' },
        thread: { anyOf: [{ type: 'string' }, { type: 'null' }], 'ui:hidden': true },
        notify: { anyOf: [{ type: 'boolean' }, { type: 'null' }] },
    },
    required: ['operation', 'channel'],
    'x-require-one-of': [[['text'], ['blocks']]],
};
const LIST = {
    title: 'List channels',
    properties: { operation: { const: 'list_channels' }, types: { type: 'array', items: { type: 'string' } } },
    required: ['operation'],
};
const STEP = {
    properties: { config: { $ref: '#/$defs/StepConfig' } },
    $defs: { StepConfig: { oneOf: [{ $ref: '#/$defs/Send' }, { $ref: '#/$defs/List' }] }, Send: SEND, List: LIST },
};

describe('schemaInfoOf', () => {
    it('resolves the config schema and finds the operation that tells the options apart', () => {
        const info = schemaInfoOf(STEP)!;
        expect(info.hasOptions).toBe(true);
        expect(info.hasDiscriminator).toBe(true);
        expect(info.discriminator.fieldName).toBe('operation');
        expect([...info.discriminator.valueToOptionIndex]).toEqual([
            ['send_message', 0],
            ['list_channels', 1],
        ]);
    });

    it('has nothing to say of a missing schema or one whose config ref resolves to nothing', () => {
        expect(schemaInfoOf(undefined)).toBeNull();
        expect(schemaInfoOf({ properties: { config: { $ref: '#/$defs/Missing' } } })).toBeNull();
    });

    it('reads a schema with no config property as its own config', () => {
        const info = schemaInfoOf({ properties: { url: { type: 'string' } }, required: ['url'] })!;
        expect(info.hasOptions).toBe(false);
        expect(fieldsForOption(info)).toEqual([{ key: 'url', prop: { type: 'string' }, required: true }]);
    });
});

describe('an operation and its fields', () => {
    const info = schemaInfoOf(STEP);

    it('lists the operations in option order', () => {
        expect(operationsOf(info)).toEqual([
            { value: 'send_message', index: 0 },
            { value: 'list_channels', index: 1 },
        ]);
        expect(operationsOf(null)).toEqual([]);
    });

    it("gives the selected operation's visible fields, by index or by value", () => {
        expect(fieldsForOption(info, 0).map((f) => [f.key, f.required])).toEqual([
            ['channel', true],
            ['notify', false],
        ]);
        expect(fieldsForOption(info, undefined, 'list_channels').map((f) => f.key)).toEqual(['operation', 'types']);
        expect(fieldsForOption(null, 0)).toEqual([]);
    });

    it("gives the operation's either-or groups", () => {
        expect(requireOneOfGroupsOf(info, undefined, 'send_message')).toEqual([[['text'], ['blocks']]]);
        expect(requireOneOfGroupsOf(info, 1)).toEqual([]);
    });

    it('names an option from its title, or its description, or its value', () => {
        expect(optionLabelOf(info, 0)).toBe('Send Message');
        expect(optionLabelOf(info, 1)).toBe('List channels');
        const untitled = schemaInfoOf({ oneOf: [{ properties: { op: { const: 'a' } }, description: 'Does a. Then more.' }, { properties: { op: { const: 'b' } } }] });
        expect(optionLabelOf(untitled, 0)).toBe('Does a');
        expect(optionLabelOf(untitled, 1)).toBe('B');
    });

    it('offers a choice of operation unless every option flattens the union', () => {
        expect(offersOperationChoice(info)).toBe(true);
        const flat = schemaInfoOf({
            oneOf: [
                { properties: { kind: { const: 'x' } }, 'x-flatten-union': true },
                { properties: { kind: { const: 'y' } }, 'x-flatten-union': true },
            ],
        });
        expect(flat?.hasDiscriminator).toBe(true);
        expect(offersOperationChoice(flat)).toBe(false);
    });

    it('shows every option\'s fields once when nothing tells the options apart', () => {
        const merged = schemaInfoOf({ anyOf: [{ properties: { a: { type: 'string' } } }, { properties: { a: { type: 'number' }, b: { type: 'string' } }, required: ['b'] }] });
        expect(merged?.hasDiscriminator).toBe(false);
        expect(fieldsForOption(merged).map((f) => [f.key, f.required])).toEqual([
            ['a', false],
            ['b', true],
        ]);
    });
});

describe('field shapes', () => {
    it('knows a boolean field, nullable or not, and not one that also takes text', () => {
        expect(isBooleanSchema({ type: 'boolean' })).toBe(true);
        expect(isBooleanSchema({ type: ['boolean', 'null'] })).toBe(true);
        expect(isBooleanSchema({ anyOf: [{ type: 'boolean' }, { type: 'null' }] })).toBe(true);
        expect(isBooleanSchema({ anyOf: [{ type: 'boolean' }, { type: 'string' }] })).toBe(false);
        expect(isBooleanSchema(null)).toBe(false);
        expect(['true', true, 'false', false, '', undefined].map(booleanSelectValue)).toEqual(['true', 'true', 'false', 'false', '', '']);
    });

    it('knows a list field and the labels its picker keeps', () => {
        expect(isListSchema({ type: 'array' })).toBe(true);
        expect(isListSchema({ anyOf: [{ type: 'array' }, { type: 'null' }] })).toBe(true);
        expect(isListSchema({ type: 'string' })).toBe(false);
        expect(listLabels({ to__label: { a: 'Ada' } }, 'to')).toEqual({ a: 'Ada' });
        expect(listLabels({ to__label: ['a'] }, 'to')).toEqual({});
    });
});
