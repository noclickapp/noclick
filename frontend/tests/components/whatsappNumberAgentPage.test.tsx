// @vitest-environment happy-dom
// A WhatsApp number's page under Connections: where a number linked with Not now gets its agent later (Create agent,
// which opens its channel), or the agent that answers it already, with its channel. Nothing where the account has no
// agents to put on it, and nothing on any other app's account.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ status: {} as Record<string, unknown>, sent: [] as Record<string, unknown>[], navigateToTab: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: vi.fn(async (event: Record<string, unknown>) => {
        state.sent.push(event);
        if (event.event_name === 'whatsapp:agent:status') return state.status;
        return { success: true, created: true, agent: { agent_id: 'a-1', name: 'WhatsApp', channel_id: 'ch-1', channel_name: 'whatsapp' } };
    }),
}));
vi.mock('~/lib/socketCall', () => ({ socketCall: vi.fn(async () => ({ shares: [] })) }));
vi.mock('~/hooks/useConnectionProbe', () => ({ useConnectionProbe: () => ({ probe: undefined, check: vi.fn(), canCheck: false }), lastConnectionProbe: () => undefined }));
vi.mock('~/lib/navigation', async (importOriginal) => ({ ...(await importOriginal<typeof import('~/lib/navigation')>()), navigateToTab: state.navigateToTab }));

import { AccountPage } from '~/components/shell/connections/AccountPage';
import type { ConnectedAccount } from '~/components/shell/connections/accounts';
import type { CredentialInfo } from '~/types/socket-events.generated';

afterEach(() => {
    cleanup();
    state.sent.length = 0;
    state.navigateToTab.mockReset();
});

const account = (credential_type = 'whatsapp_qr'): ConnectedAccount => ({
    credential: { id: 'wa-1', name: 'WhatsApp (+12025550101)', credential_type, metadata: {}, created_at: '2026-11-14T09:00:00Z', updated_at: '2026-11-14T09:00:00Z', access_type: 'owner' } as CredentialInfo,
    app: 'WhatsApp',
    line: 'WhatsApp · +1 202 555 0101',
    source: 'connected',
});

const page = (credentialType?: string) =>
    render(
        <MemoryRouter>
            <AccountPage account={account(credentialType)} backLabel="Connected" onBack={() => undefined} onGone={() => undefined} />
        </MemoryRouter>
    );

describe('a WhatsApp number’s agent on its page', () => {
    it('offers one for a number with none, and Create makes it and opens its channel', async () => {
        state.status = { success: true, available: true, agent: null };
        page();
        expect(await screen.findByText('No agent on this number')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
        await waitFor(() => expect(state.navigateToTab).toHaveBeenCalledWith('work', { show: 'home', channel: 'ch-1', thread: null }));
        expect(state.sent).toContainEqual({ event_name: 'whatsapp:agent:create', credential_id: 'wa-1' });
    });

    it('shows the agent that answers it, with its channel', async () => {
        state.status = { success: true, available: true, agent: { agent_id: 'a-9', name: 'Front desk', channel_id: 'ch-9', channel_name: 'front-desk' } };
        page();
        expect(await screen.findByText('Front desk answers this number')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Create agent' })).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Open its channel' }));
        expect(state.navigateToTab).toHaveBeenCalledWith('work', { show: 'home', channel: 'ch-9', thread: null });
    });

    it('says nothing where the account has no agents, or on another app’s account', async () => {
        state.status = { success: true, available: false, agent: null };
        page();
        await waitFor(() => expect(state.sent).toHaveLength(1));
        expect(screen.queryByText('Agent')).toBeNull();
        cleanup();
        state.sent.length = 0;
        page('gmail_oauth');
        expect(state.sent.filter((e) => String(e.event_name).startsWith('whatsapp:'))).toEqual([]);
    });
});
