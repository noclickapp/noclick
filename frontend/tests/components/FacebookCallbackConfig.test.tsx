// @vitest-environment jsdom
// Exercise the generated Facebook schema through the real configuration editor.
// These cases guard Page/mode changes and stale registration responses in both editions.
import React from 'react';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';

const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({
    useAgentCredentialsRequired: () => ({ credentialsRequired: false, allowUsageBased: false, provider: null }),
}));

const credentials = { facebook_oauth: '11111111-1111-4111-8111-111111111111' };
const props = {
    nodeType: 'automation-facebook', nodeId: 'fb-test', workflowId: 'wf-test',
    operation: 'on_feed', credentialIds: credentials, onChange: vi.fn(),
};
const registrations = () => mocks.send.mock.calls.map(([request]) => request)
    .filter(request => request.event_name === 'workflow:node:load_value');

beforeEach(() => {
    mocks.send.mockReset();
    props.onChange.mockReset();
    mocks.send.mockImplementation(async request => {
        if (request.event_name === 'workflow:node:load_value') {
            return { success: true, value: `Registered Page ${request.context.page_id}` };
        }
        return { success: true, valid: true, errors: [], options: [] };
    });
});
afterEach(cleanup);

describe('Facebook callback setup uses the real generated schema and NodeConfig', () => {
    it('does not register hidden managed status for a legacy/manual trigger', async () => {
        const { container } = render(<NodeConfig {...props} config={{}} />);
        await waitFor(() => expect(container.querySelector('[data-field-key="verify_token"]')).not.toBeNull());
        expect(container.querySelector('[data-field-key="page_id"]')).toBeNull();
        expect(registrations().filter(r => r.field_name === 'subscription_status')).toHaveLength(0);
    });

    it('reloads status when switching modes or Pages without changing credential', async () => {
        const { rerender, container } = render(<NodeConfig {...props} config={{ callback_mode: 'manual' }} />);
        rerender(<NodeConfig {...props} config={{ callback_mode: 'managed', page_id: '101' }} />);
        await waitFor(() => expect(registrations().some(r => r.context.page_id === '101')).toBe(true));
        expect(container.querySelector('[data-field-key="verify_token"]')).toBeNull();
        expect(container.querySelector('[data-field-key="page_id"]')).not.toBeNull();
        rerender(<NodeConfig {...props} config={{ callback_mode: 'managed', page_id: '202' }} />);
        await waitFor(() => expect(registrations().some(r => r.context.page_id === '202')).toBe(true));
        expect(registrations().every(r => r.credential_ids === credentials)).toBe(true);
    });

    it('discards an old Page response and fetches the latest Page after it finishes', async () => {
        let finish!: (value: unknown) => void;
        mocks.send.mockImplementation(async request => {
            if (request.event_name !== 'workflow:node:load_value') return { success: true, valid: true, options: [] };
            if (request.context.page_id === '101') return new Promise(resolve => { finish = resolve; });
            return { success: true, value: 'Registered Page 202' };
        });
        const { rerender } = render(<NodeConfig {...props} config={{ callback_mode: 'managed', page_id: '101' }} />);
        await waitFor(() => expect(finish).toBeTypeOf('function'));
        rerender(<NodeConfig {...props} config={{ callback_mode: 'managed', page_id: '202' }} />);
        await act(async () => { finish({ success: true, value: 'Registered Page 101' }); });
        await waitFor(() => expect(registrations().some(r => r.context.page_id === '202')).toBe(true));
        await waitFor(() => expect(props.onChange.mock.calls.some(([config]) => config.subscription_status === 'Registered Page 202')).toBe(true));
        expect(props.onChange.mock.calls.some(([config]) => config.subscription_status === 'Registered Page 101')).toBe(false);
    });

    it('does not persist a managed response after switching to manual', async () => {
        let finish!: (value: unknown) => void;
        mocks.send.mockImplementation(async request => {
            if (request.event_name !== 'workflow:node:load_value') return { success: true, valid: true, options: [] };
            return new Promise(resolve => { finish = resolve; });
        });
        const { rerender } = render(<NodeConfig {...props} config={{ callback_mode: 'managed', page_id: '101' }} />);
        await waitFor(() => expect(finish).toBeTypeOf('function'));
        rerender(<NodeConfig {...props} config={{ callback_mode: 'manual' }} />);
        await act(async () => { finish({ success: true, value: 'Registered Page 101' }); });
        expect(props.onChange.mock.calls.some(([config]) => config.subscription_status === 'Registered Page 101')).toBe(false);
    });

    it('clears a saved status while verifying a different Page', async () => {
        let finish!: (value: unknown) => void;
        mocks.send.mockImplementation(async request => {
            if (request.event_name !== 'workflow:node:load_value') return { success: true, valid: true, options: [] };
            return new Promise(resolve => { finish = resolve; });
        });
        const { container } = render(<NodeConfig {...props} config={{
            callback_mode: 'managed', page_id: '202', subscription_status: 'Registered Page 101',
        }} />);
        await waitFor(() => expect(finish).toBeTypeOf('function'));
        expect(container.textContent).not.toContain('Registered Page 101');
        expect(container.querySelector<HTMLInputElement>('[data-field-key="subscription_status"] input')?.value).not.toBe('Registered Page 101');
        await act(async () => { finish({ success: false, message: 'Page verification failed' }); });
        expect(props.onChange.mock.calls.some(([config]) => config.subscription_status === 'Registered Page 101')).toBe(false);
    });

    it('does not apply registration after the panel unmounts', async () => {
        let finish!: (value: unknown) => void;
        mocks.send.mockImplementation(async request => {
            if (request.event_name !== 'workflow:node:load_value') return { success: true, valid: true, options: [] };
            return new Promise(resolve => { finish = resolve; });
        });
        const { unmount } = render(<NodeConfig {...props} config={{ callback_mode: 'managed', page_id: '101' }} />);
        await waitFor(() => expect(finish).toBeTypeOf('function'));
        unmount();
        await act(async () => { finish({ success: true, value: 'Registered Page 101' }); });
        expect(props.onChange.mock.calls.some(([config]) => config.subscription_status === 'Registered Page 101')).toBe(false);
    });
});
