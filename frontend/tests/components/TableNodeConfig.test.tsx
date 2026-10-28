// @vitest-environment jsdom
// The Table step's form through the real NodeConfig and its generated schema: its picker lists the open
// workflow's tables (the request names that workflow), a name not listed yet is a new table rather than a
// value "not found", and an object typed as JSON text validates as the runtime reads it.
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { WorkflowProvider } from '~/components/workflow/WorkflowContext';

const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/analytics', () => ({
    useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }),
}));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({
    useAgentCredentialsRequired: () => ({
        credentialsRequired: false,
        allowUsageBased: false,
        provider: null,
    }),
}));

const optionLoads = () =>
    mocks.send.mock.calls
        .map(([request]) => request)
        .filter(
            (request) => request.event_name === 'workflow:node:load_options'
        );

function renderTable(
    operation: string,
    config: Record<string, unknown>,
    onValidationChange = vi.fn()
) {
    return render(
        <WorkflowProvider workflowId="wf-test" workflowName="Sweep">
            <NodeConfig
                nodeType="automation-table"
                nodeId="save"
                workflowId="wf-test"
                operation={operation}
                config={config}
                onChange={vi.fn()}
                onValidationChange={onValidationChange}
            />
        </WorkflowProvider>
    );
}

beforeEach(() => {
    mocks.send.mockReset();
    mocks.send.mockImplementation(async (request) =>
        request.event_name === 'workflow:node:load_options'
            ? {
                  success: true,
                  options: [{ value: 'Leads', label: 'Leads' }],
                  next_page_token: null,
              }
            : { success: true, valid: true, errors: [], options: [] }
    );
});
afterEach(cleanup);

describe('Table step form', () => {
    it("lists the open workflow's tables and takes a new name without a warning", async () => {
        const { container } = renderTable('add_rows', {
            table: 'Results',
            rows: '[{"title": "Ada"}]',
        });
        await waitFor(() => expect(optionLoads().length).toBeGreaterThan(0));
        expect(optionLoads()[0]).toMatchObject({
            node_type: 'automation-table',
            field_name: 'table',
            workflow_id: 'wf-test',
        });
        await act(async () => {
            await mocks.send.mock.results.at(-1)?.value;
        });
        expect(
            (
                container.querySelector(
                    'input[data-field-key="table"]'
                ) as HTMLInputElement
            ).value
        ).toBe('Results');
        expect(container.textContent).not.toContain('not found in options');
    });

    it('validates an object written as JSON text', async () => {
        const onValidationChange = vi.fn();
        renderTable(
            'update_rows',
            { table: 'Leads', row_id: 'r-1', values: '{"status": "done"}' },
            onValidationChange
        );
        await waitFor(() => expect(onValidationChange).toHaveBeenCalled());
        expect(onValidationChange).toHaveBeenLastCalledWith(true);
    });
});
