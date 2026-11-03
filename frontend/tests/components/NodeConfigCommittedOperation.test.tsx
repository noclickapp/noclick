// @vitest-environment jsdom
// The config panel judges a node's fields against its COMMITTED operation from the first render.
// A WhatsApp QR trigger (receive_message, nothing required) used to be validated once against the
// schema's first variant (send_text_message: to + body), flashing two false field errors on every open.
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { EVENTS } from '~/lib/analytics-events';

const mocks = vi.hoisted(() => ({ send: vi.fn(), logActivity: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ logActivity: mocks.logActivity }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({
    useAgentCredentialsRequired: () => ({ credentialsRequired: false, allowUsageBased: false, provider: null }),
}));

// A connected QR trigger as saved: config + the runtime mirrors its registration writes back.
const savedTriggerConfig = {
    include_group_messages: 'false',
    verify_token: '',
    webhook_id: '00000000-0000-4000-8000-000000000001',
    is_active: true,
    secret_set: false,
    is_production: true,
    relay_connected: true,
    wahooks_registered: true,
    trigger_registered: true,
    trigger_error: '',
    registered_operation: 'receive_message',
    registered_credential_id: '00000000-0000-4000-8000-000000000002',
    paused_by: null,
    paused_reason: null,
};

const errorShownCalls = () => mocks.logActivity.mock.calls.filter(([event]) => event === EVENTS.NODE_CONFIG_ERROR_SHOWN);

// Resolves once the form (lazy-loaded node schemas) has mounted and settled.
async function renderWhatsApp(operation: string, config: Record<string, unknown>, fieldKey: string) {
    const onValidationStateChange = vi.fn();
    const { container } = render(
        <NodeConfig
            nodeType="automation-whatsapp"
            nodeId="wa-trigger"
            workflowId="wf-test"
            operation={operation}
            config={config}
            credentialIds={{ whatsapp_qr: '00000000-0000-4000-8000-000000000002' }}
            onChange={vi.fn()}
            onValidationStateChange={onValidationStateChange}
        />,
    );
    await waitFor(() => expect(container.querySelector(`[data-field-key="${fieldKey}"]`)).not.toBeNull());
    return onValidationStateChange;
}

beforeEach(() => {
    mocks.logActivity.mockReset();
    mocks.send.mockReset();
    mocks.send.mockResolvedValue({ success: true, valid: true, errors: [], options: [] });
});
afterEach(cleanup);

describe('NodeConfig validates the committed operation from the first render', () => {
    it('never reports field errors for a valid WhatsApp QR receive_message trigger', async () => {
        const onValidationStateChange = await renderWhatsApp('receive_message', savedTriggerConfig, 'include_group_messages');
        expect(errorShownCalls()).toEqual([]);
        expect(onValidationStateChange.mock.calls.every(([state]) => state.valid)).toBe(true);
    });

    it('still reports the required fields of the operation actually committed', async () => {
        const onValidationStateChange = await renderWhatsApp('send_text_message', {}, 'body');
        expect(errorShownCalls()).toHaveLength(1);
        expect(errorShownCalls()[0][1]).toMatchObject({
            node_type: 'automation-whatsapp',
            error_types: ['field'],
            error_count: 2,
        });
        expect(onValidationStateChange.mock.lastCall?.[0].valid).toBe(false);
    });
});
