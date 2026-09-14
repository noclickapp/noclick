// @vitest-environment jsdom
// Setup distinguishes configuration from actual input and processing evidence.
// Refresh cannot retain another workflow's old success badge.
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkflowReadinessStatus } from '~/components/workflow/setup/WorkflowReadinessStatus';
const send = vi.hoisted(() => vi.fn());
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: send }));
afterEach(() => {
    cleanup();
    send.mockReset();
});

it('shows waiting, restricted recipient, and the distinction between acceptance and delivery', async () => {
    send.mockResolvedValue({
        readiness: {
            status: 'waiting_for_input',
            issues: [],
            observations: [],
            destinations: [
                {
                    node_id: 'alerts',
                    operation: 'send_text_message',
                    recipients: ['manager@lid'],
                },
            ],
        },
    });
    render(<WorkflowReadinessStatus workflowId="wf" />);
    await screen.findByText('Registered — waiting for a real input');
    expect(
        screen.getByText('Restricted alert destination: manager@lid')
    ).toBeTruthy();
    expect(screen.getByText(/Test Runs are simulated/)).toBeTruthy();
    expect(send).toHaveBeenCalledWith({
        event_name: 'workflow:get',
        workflow_id: 'wf',
        include_readiness: true,
    });
    send.mockResolvedValue({
        readiness: {
            status: 'input_observed',
            issues: [],
            destinations: [],
            observations: [
                {
                    node_id: 'in',
                    created_at: '2026-09-14T09:00:00Z',
                    run_status: 'error',
                },
            ],
        },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await screen.findByText(/Processing: error/);
});

it('drops stale success when changing workflows and surfaces verification failure', async () => {
    send.mockResolvedValueOnce({
        readiness: {
            status: 'input_observed',
            issues: [],
            destinations: [],
            observations: [],
        },
    });
    const view = render(<WorkflowReadinessStatus workflowId="old" />);
    await screen.findByText('Real input observed');
    send.mockRejectedValueOnce(new Error('Disconnected'));
    view.rerender(<WorkflowReadinessStatus workflowId="new" />);
    await screen.findByText('Disconnected');
    expect(screen.queryByText('Real input observed')).toBeNull();
});
