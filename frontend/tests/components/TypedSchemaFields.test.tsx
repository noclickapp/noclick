// @vitest-environment jsdom

import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NodeConfig, NodeConfigFieldControl } from '~/components/workflow/NodeConfig';
import { renderGenerationField } from '~/components/workflow/schemaFieldRenderer';
import { applyNodeUpdate, buildSaveConfig, createWorkflowNode } from '~/lib/applyNodeUpdate';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ success: true, valid: true, errors: [], options: [] })) }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({ useAgentCredentialsRequired: () => ({ credentialsRequired: false, allowUsageBased: false, provider: null }) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

afterEach(() => { cleanup(); delete NODE_SCHEMAS['typed-field-fixture']; });

function FieldHarness({ schema, initial, variant = 'editor', onEdit }: { schema: any; initial?: unknown; variant?: 'editor' | 'generation'; onEdit?: (key: string, value: unknown) => void }) {
    const [node, setNode] = useState(() => createWorkflowNode('typed-field', 'typed-field-fixture', { x: 0, y: 0 }, { value: initial }));
    const config = node.data.config as Record<string, unknown>;
    const onChange = (key: string, value: unknown) => {
        onEdit?.(key, value);
        setNode(current => applyNodeUpdate(current, { config: { [key]: value }, preserveConfigNulls: true }));
    };
    const saved = JSON.parse(JSON.stringify(buildSaveConfig(node)));
    return <>
        {variant === 'editor'
            ? <NodeConfigFieldControl fieldKey="value" prop={schema} value={config.value} nodeType="typed-field-fixture" onChange={onChange} />
            : renderGenerationField({ fieldKey: 'value', fieldSchema: schema, value: config.value, onChange })}
        <output data-testid="saved">{JSON.stringify(saved)}</output>
        <button onClick={() => setNode(createWorkflowNode('typed-field', 'typed-field-fixture', { x: 0, y: 0 }, saved))}>Reload saved config</button>
    </>;
}

function savedValue() { return JSON.parse(screen.getByTestId('saved').textContent || '{}').value; }
function choose(label: string) {
    const option = screen.getByRole('option', { name: label }) as HTMLOptionElement;
    fireEvent.change(option.parentElement!, { target: { value: option.value } });
}

function NativePanelHarness() {
    const [node, setNode] = useState(() => createWorkflowNode('native-panel', 'automation-reddit', { x: 0, y: 0 }, {
        operation: 'sticky_or_unsticky_post', thing_id: 't3_fixture', num: 1, state: false,
    }));
    const saved = JSON.parse(JSON.stringify(buildSaveConfig(node)));
    return <>
        <NodeConfig nodeType="automation-reddit" nodeId="native-panel" config={node.data.config as any}
            operation={node.data.operation as string} onChange={config => setNode(current => applyNodeUpdate(current, { config, preserveConfigNulls: true }))} />
        <output data-testid="saved">{JSON.stringify(saved)}</output>
        <button onClick={() => setNode(createWorkflowNode('native-panel', 'automation-reddit', { x: 0, y: 0 }, saved))}>Reload saved config</button>
    </>;
}

describe.each(['editor', 'generation'] as const)('%s typed controls preserve save and hydration values', variant => {
    it('preserves numeric zero and selects a number without confusing a string enum', () => {
        render(<FieldHarness variant={variant} schema={{ enum: [0, 1, '1'], enumNames: ['Zero', 'Number one', 'String one'] }} initial={0} />);
        expect((screen.getByRole('combobox') as HTMLSelectElement).selectedOptions[0].text).toBe('Zero');
        choose('Number one');
        expect(savedValue()).toBe(1);
        fireEvent.click(screen.getByText('Reload saved config'));
        expect((screen.getByRole('combobox') as HTMLSelectElement).selectedOptions[0].text).toBe('Number one');
        choose('String one');
        expect(savedValue()).toBe('1');
    });

    it('uses a nullable numeric native schema and retains an explicit null', () => {
        const schema = NODE_SCHEMAS['automation-reddit'].$defs.RedditStickyPostConfig.properties.num;
        render(<FieldHarness variant={variant} schema={schema} initial={null} />);
        choose('2');
        expect(savedValue()).toBe(2);
        choose('None');
        expect(savedValue()).toBeNull();
        fireEvent.click(screen.getByText('Reload saved config'));
        expect((screen.getByRole('combobox') as HTMLSelectElement).selectedOptions[0].text).toBe('None');
    });

    it.each([
        { type: ['boolean', 'null'] },
        { anyOf: [{ type: 'boolean' }, { type: 'null' }] },
        { oneOf: [{ type: 'boolean' }, { type: 'null' }] },
    ])('writes true, false and null from a nullable boolean schema %#', schema => {
        render(<FieldHarness variant={variant} schema={schema} initial={false} />);
        choose('Yes'); expect(savedValue()).toBe(true);
        choose('No'); expect(savedValue()).toBe(false);
        choose('None'); expect(savedValue()).toBeNull();
        choose('Not set'); expect(savedValue()).toBeUndefined();
    });

    it('does not offer false for a true-only enum', () => {
        render(<FieldHarness variant={variant} schema={{ type: 'boolean', enum: [true] }} />);
        expect(screen.queryByRole('option', { name: 'false' })).toBeNull();
        choose('true'); expect(savedValue()).toBe(true);
    });

    it('selects and removes numeric and boolean array items with their original types', () => {
        render(<FieldHarness variant={variant} schema={{ anyOf: [{ type: 'array', items: { enum: [0, 2, false, true], enumNames: ['Zero', 'Two', 'Disabled', 'Enabled'] } }, { type: 'null' }] }} initial={[0]} />);
        fireEvent.click(screen.getByText('Select one or more...'));
        fireEvent.click(screen.getByRole('button', { name: 'Two' }));
        fireEvent.click(screen.getByRole('button', { name: 'Disabled' }));
        expect(savedValue()).toEqual([0, 2, false]);
        fireEvent.click(screen.getByRole('button', { name: 'Remove Zero' }));
        expect(savedValue()).toEqual([2, false]);
        fireEvent.click(screen.getByText('Reload saved config'));
        expect(savedValue()).toEqual([2, false]);
        expect(screen.getByRole('button', { name: 'Remove Disabled' })).toBeTruthy();
    });

    it('preserves the legacy top-level string array enum contract', () => {
        render(<FieldHarness variant={variant} schema={{ type: 'array', enum: ['create', 'change'], enumNames: ['Created', 'Changed'] }} initial={['create']} />);
        fireEvent.click(screen.getByText('Select one or more...'));
        fireEvent.click(screen.getByRole('button', { name: 'Changed' }));
        expect(savedValue()).toEqual(['create', 'change']);
    });

    it('keeps unmatched stored strings unchanged during hydration', () => {
        const changed = vi.fn();
        render(<FieldHarness variant={variant} schema={{ type: 'integer', enum: [1, 2] }} initial="2" onEdit={changed} />);
        expect(savedValue()).toBe('2');
        fireEvent.click(screen.getByText('Reload saved config'));
        expect(savedValue()).toBe('2');
        expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('');
        expect(changed).not.toHaveBeenCalled();
    });
});

describe('actual editor searchable enum and validation paths', () => {
    it('edits and reloads the current native Reddit numeric enum through the complete NodeConfig panel', async () => {
        const { container } = render(<NativePanelHarness />);
        const select = container.querySelector<HTMLSelectElement>('select[data-field-key="num"]')!;
        expect(select).not.toBeNull();
        const state = container.querySelector<HTMLSelectElement>('select[data-field-key="state"]')!;
        expect(state.selectedOptions[0].text).toBe('No');
        const option = [...select.options].find(option => option.text === '2')!;
        fireEvent.change(select, { target: { value: option.value } });
        await waitFor(() => expect(JSON.parse(screen.getByTestId('saved').textContent!).num).toBe(2));
        fireEvent.click(screen.getByText('Reload saved config'));
        expect(select.selectedOptions[0].text).toBe('2');
        const none = [...select.options].find(option => option.text === 'None')!;
        fireEvent.change(select, { target: { value: none.value } });
        await waitFor(() => expect(JSON.parse(screen.getByTestId('saved').textContent!).num).toBeNull());
        fireEvent.click(screen.getByText('Reload saved config'));
        expect(select.selectedOptions[0].text).toBe('None');
        expect(JSON.parse(screen.getByTestId('saved').textContent!).state).toBe(false);
    });

    it.each(['5garbage', '1.5', '1.', '9007199254740993', 'Infinity'])('keeps an invalid integer edit as text: %s', text => {
        render(<FieldHarness schema={{ type: 'integer' }} />);
        fireEvent.change(screen.getByRole('textbox'), { target: { value: text } });
        expect(savedValue()).toBe(text);
    });

    it('parses complete numeric edits and preserves expressions', () => {
        render(<FieldHarness schema={{ type: 'number' }} />);
        const input = screen.getByRole('textbox');
        fireEvent.change(input, { target: { value: '0' } }); expect(savedValue()).toBe(0);
        fireEvent.change(input, { target: { value: '-1.25e2' } }); expect(savedValue()).toBe(-125);
        fireEvent.change(input, { target: { value: "{{ $('source').count }}" } });
        expect(savedValue()).toBe("{{ $('source').count }}");
    });

    it('leaves a boolean/string union as a text field', () => {
        render(<FieldHarness schema={{ anyOf: [{ type: 'boolean' }, { type: 'string' }] }} initial="false" />);
        expect(screen.queryByRole('combobox')).toBeNull();
        expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('false');
        expect(savedValue()).toBe('false');
    });

    it('searches numeric/boolean options and emits their actual typed values', () => {
        render(<FieldHarness schema={{ enum: [0, 5, false], enumNames: ['Zero', 'Five', 'Disabled'], 'x-enum-searchable': true }} initial={0} />);
        const input = screen.getByRole('textbox');
        expect((input as HTMLInputElement).value).toBe('Zero');
        fireEvent.focus(input);
        fireEvent.click(screen.getByRole('button', { name: 'Five' }));
        expect(savedValue()).toBe(5);
        fireEvent.click(input);
        fireEvent.click(screen.getByRole('button', { name: 'Disabled' }));
        expect(savedValue()).toBe(false);
    });

    it('preserves free text and references instead of parsing arbitrary enum input', () => {
        render(<FieldHarness schema={{ type: 'integer', enum: [1, 5], 'x-enum-searchable': true }} />);
        const input = screen.getByRole('textbox');
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: '5garbage' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(savedValue()).toBe('5garbage');
        fireEvent.click(input);
        fireEvent.change(input, { target: { value: "{{ $('source').count }}" } });
        expect(savedValue()).toBe("{{ $('source').count }}");
    });

    it('does not coerce saved numeric or boolean array strings while validating the mounted panel', async () => {
        NODE_SCHEMAS['typed-field-fixture'] = { properties: { config: { type: 'object', properties: {
            interval: { type: 'integer', enum: [1, 5] },
            active: { anyOf: [{ type: 'boolean' }, { type: 'null' }] },
            numbers: { type: 'array', items: { type: 'integer', enum: [1, 5] } },
            flags: { type: 'array', items: { type: 'boolean' } },
        } } } } as any;
        const config = { interval: '5', active: 'false', numbers: ['1'], flags: ['false'] };
        const validation = vi.fn();
        const change = vi.fn();
        const { rerender } = render(<NodeConfig nodeType="typed-field-fixture" nodeId="typed-panel" config={config} onChange={change} onValidationChange={validation} />);
        await waitFor(() => expect(validation).toHaveBeenLastCalledWith(false));
        expect(config).toEqual({ interval: '5', active: 'false', numbers: ['1'], flags: ['false'] });
        const node = createWorkflowNode('typed-panel', 'typed-field-fixture', { x: 0, y: 0 }, config);
        expect(JSON.parse(JSON.stringify(buildSaveConfig(node)))).toEqual(config);
        expect(change).not.toHaveBeenCalled();
        rerender(<NodeConfig nodeType="typed-field-fixture" nodeId="typed-panel" config={{ interval: 5, active: false, numbers: [1], flags: [false] }} onChange={change} onValidationChange={validation} />);
        await waitFor(() => expect(validation).toHaveBeenLastCalledWith(true));
        expect(config).toEqual({ interval: '5', active: 'false', numbers: ['1'], flags: ['false'] });
    });
});
