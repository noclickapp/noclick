// @vitest-environment jsdom
// A working trigger must open in the config panel with no field errors, not even
// for a frame: the panel used to judge every operation-based node against its
// FIRST action on mount (a WhatsApp trigger read "To" and "Message Text" as
// missing), which fired the error analytics on every open and read as broken.
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { WorkflowProvider } from '~/components/workflow/WorkflowContext';
import { EVENTS } from '~/lib/analytics-events';

const mocks = vi.hoisted(() => ({ send: vi.fn(), logActivity: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/analytics', () => ({
    useAnalytics: () => ({ track: vi.fn(), logActivity: mocks.logActivity }),
}));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({
    useAgentCredentialsRequired: () => ({ credentialsRequired: false, allowUsageBased: false, provider: null }),
}));

const WHATSAPP_TRIGGER = {
    webhook_id: 'wh-1',
    webhook_url: 'https://wh-1.example.run',
    wahooks_registered: true,
    trigger_registered: true,
    is_active: true,
    include_group_messages: 'false',
};

const DAILY_SCHEDULE = {
    timezone: 'Asia/Jerusalem',
    schedules: [{ hour: 9, minute: 0, frequency: 'day' }],
    schedule_id: 'sched-1',
    webhook_url: 'https://wh-2.example.run',
    trigger_registered: true,
    next_run: '2026-11-01T07:00:00Z',
};

function open(nodeType: string, operation: string | undefined, config: Record<string, unknown>, credentialIds: Record<string, string>, onValidationChange: (valid: boolean) => void) {
    return render(
        <WorkflowProvider workflowId="wf-test" workflowName="Triggers">
            <NodeConfig
                nodeType={nodeType}
                nodeId="trigger"
                workflowId="wf-test"
                operation={operation}
                config={config}
                credentialIds={credentialIds}
                onChange={vi.fn()}
                onValidationChange={onValidationChange}
            />
        </WorkflowProvider>
    );
}

// Wait for the form to draw (its schema loads first), then let its mount
// effects (operation sync, validation, analytics) run out.
async function settle(onValidationChange: ReturnType<typeof vi.fn>) {
    await waitFor(() => expect(onValidationChange).toHaveBeenCalled());
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

const errorEvents = () =>
    mocks.logActivity.mock.calls.filter(([event]) => event === EVENTS.NODE_CONFIG_ERROR_SHOWN).map(([, props]) => props);

beforeEach(() => {
    mocks.send.mockReset();
    mocks.logActivity.mockReset();
    mocks.send.mockResolvedValue({ success: true, valid: true, errors: [], options: [] });
});
afterEach(cleanup);

describe('opening a working trigger', () => {
    it('shows a WhatsApp message trigger with no field errors', async () => {
        const onValidationChange = vi.fn();
        const { container } = open('automation-whatsapp', 'receive_message', WHATSAPP_TRIGGER, { whatsapp_qr: 'cred-1' }, onValidationChange);
        await settle(onValidationChange);
        expect(onValidationChange).toHaveBeenCalledWith(true);
        expect(onValidationChange).not.toHaveBeenCalledWith(false);
        expect(errorEvents()).toEqual([]);
        expect(container.textContent).not.toContain('Complete required fields');
        expect(container.querySelector('[data-field-key="to"]')).toBeNull();
    });

    it('shows a registered schedule in a zone outside the shortlist with no field errors', async () => {
        const onValidationChange = vi.fn();
        const { container } = open('trigger-cron', undefined, DAILY_SCHEDULE, {}, onValidationChange);
        await settle(onValidationChange);
        expect(onValidationChange).toHaveBeenCalledWith(true);
        expect(onValidationChange).not.toHaveBeenCalledWith(false);
        expect(errorEvents()).toEqual([]);
        expect(container.textContent).not.toContain('Complete required fields');
    });

    it('still reports an incomplete send step', async () => {
        const onValidationChange = vi.fn();
        const { container } = open('automation-whatsapp', 'send_text_message', {}, { whatsapp_qr: 'cred-1' }, onValidationChange);
        await settle(onValidationChange);
        expect(errorEvents()).toHaveLength(1);
        expect(onValidationChange).toHaveBeenLastCalledWith(false);
        expect(errorEvents()[0]).toMatchObject({ node_type: 'automation-whatsapp', error_count: 2, error_types: ['field'] });
        expect(container.textContent).toContain('To (Phone or Chat)');
        expect(container.textContent).toContain('Message Text');
    });
});
