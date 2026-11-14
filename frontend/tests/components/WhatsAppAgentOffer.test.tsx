// @vitest-environment happy-dom
// The Connect dialog's last step for a WhatsApp number linked for the account itself: the offer of an agent under the
// connected verdict, Not now (and where to add one later), a number an agent already answers (no second offer), a
// create that fails (the number stays connected, the button tries again), and an account with no agents (Done alone).
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const navigateToTab = vi.hoisted(() => vi.fn());
vi.mock('~/lib/navigation', async (importOriginal) => ({ ...(await importOriginal<typeof import('~/lib/navigation')>()), navigateToTab }));

import { WhatsAppAgentOffer } from '~/components/credential/connect/WhatsAppAgentOffer';

afterEach(() => {
    cleanup();
    navigateToTab.mockReset();
});

const AGENT = { agent_id: 'a-1', name: 'WhatsApp', channel_id: 'ch-1', channel_name: 'whatsapp' };

/** The platform's answers, as the socket would give them: `status`, then each create in turn. */
function platform(status: Record<string, unknown>, ...creates: Record<string, unknown>[]) {
    return vi.fn(async (ask: { event_name: string }) => (ask.event_name === 'whatsapp:agent:status' ? status : (creates.shift() ?? null)));
}

describe('WhatsAppAgentOffer', () => {
    it('offers an agent, and Not now leaves the number connected with where to add one later', async () => {
        const send = platform({ success: true, available: true, agent: null });
        const onDone = vi.fn();
        render(<WhatsAppAgentOffer credentialId="cred-1" onDone={onDone} transport={send as never} />);
        expect(await screen.findByText('Put an agent on this number?')).toBeTruthy();
        expect(screen.getByText('It answers your WhatsApp messages for you and lives in its own channel, where you tell it what to do.')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Create agent' })).toBeTruthy();

        fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
        expect(screen.getByText('No agent on it. You can add one later from the number in Connections.')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Create agent' })).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Done' }));
        expect(onDone).toHaveBeenCalledOnce();
        expect(send).toHaveBeenCalledTimes(1);
        expect(navigateToTab).not.toHaveBeenCalled();
    });

    it('shows the agent that already answers the number, with its channel, and offers no second one', async () => {
        const send = platform({ success: true, available: true, agent: AGENT });
        const onDone = vi.fn();
        render(<WhatsAppAgentOffer credentialId="cred-1" onDone={onDone} transport={send as never} />);
        expect(await screen.findByText('WhatsApp answers this number')).toBeTruthy();
        expect(screen.queryByText('Put an agent on this number?')).toBeNull();
        expect(screen.queryByRole('button', { name: 'Create agent' })).toBeNull();

        fireEvent.click(screen.getByRole('button', { name: 'Open its channel' }));
        expect(navigateToTab).toHaveBeenCalledWith('work', { show: 'home', channel: 'ch-1', thread: null });
        expect(onDone).toHaveBeenCalledOnce();
    });

    it('says a failed create left the number connected, and its button tries again', async () => {
        const send = platform({ success: true, available: true, agent: null }, { success: false, message: 'boom' }, { success: true, created: true, agent: AGENT });
        const onDone = vi.fn();
        render(<WhatsAppAgentOffer credentialId="cred-1" onDone={onDone} transport={send as never} />);
        fireEvent.click(await screen.findByRole('button', { name: 'Create agent' }));
        expect((await screen.findByRole('alert')).textContent).toContain('Couldn’t create the agent. Your number is still connected.');
        fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
        await waitFor(() => expect(navigateToTab).toHaveBeenCalledWith('work', { show: 'home', channel: 'ch-1', thread: null }));
        expect(onDone).toHaveBeenCalledOnce();
        expect(send.mock.calls.map(([ask]) => ask)).toEqual([
            { event_name: 'whatsapp:agent:status', credential_id: 'cred-1' },
            { event_name: 'whatsapp:agent:create', credential_id: 'cred-1' },
            { event_name: 'whatsapp:agent:create', credential_id: 'cred-1' },
        ]);
    });

    it('a create that finds an agent already on the number shows that one, opening nothing', async () => {
        const send = platform({ success: true, available: true, agent: null }, { success: true, created: false, agent: AGENT });
        render(<WhatsAppAgentOffer credentialId="cred-1" onDone={vi.fn()} transport={send as never} />);
        fireEvent.click(await screen.findByRole('button', { name: 'Create agent' }));
        expect(await screen.findByText('WhatsApp answers this number')).toBeTruthy();
        expect(navigateToTab).not.toHaveBeenCalled();
    });

    it('an account with no agents to put on it gets Done alone', async () => {
        const send = platform({ success: true, available: false, agent: null });
        render(<WhatsAppAgentOffer credentialId="cred-1" onDone={vi.fn()} transport={send as never} />);
        await waitFor(() => expect(screen.queryByTestId('whatsapp-agent-offer')).toBeNull());
        await waitFor(() => expect(screen.getByRole('button', { name: 'Done' })).toBeTruthy());
        expect(screen.queryByText('Put an agent on this number?')).toBeNull();
    });
});
