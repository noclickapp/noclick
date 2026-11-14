// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WhatsAppQRCredentialForm } from '~/components/workflow/WhatsAppQRCredentialForm';

const socketSend = vi.hoisted(() => vi.fn());
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: socketSend }));

// Every whatsapp:qr:start mints a WAHooks connection, and scanning it rebinds
// an already-linked phone's credential to that connection (2026-08-29: two
// needless re-scans from a panel that showed a QR beside a healthy credential).
// The form must not mint one unasked when a usable credential exists.
describe('WhatsAppQRCredentialForm', () => {
    afterEach(cleanup);

    const transport = () => {
        const send = vi.fn(async (payload: Record<string, unknown>) => {
            if (payload.event_name === 'whatsapp:qr:start') {
                return { success: true, connection_id: 'conn-1', qr_code: 'QR' };
            }
            return { success: true, status: 'pending' };
        });
        return send;
    };

    it('mints a QR on mount by default', async () => {
        const send = transport();
        render(<WhatsAppQRCredentialForm credentialType="whatsapp_qr" onCredentialCreated={() => {}} sendEvent={send as never} />);
        await waitFor(() => expect(send).toHaveBeenCalledWith({ event_name: 'whatsapp:qr:start' }));
        expect(await screen.findByAltText('WhatsApp QR Code')).toBeTruthy();
    });

    it('idles behind a button when autoStart is false, and only mints on click', async () => {
        const send = transport();
        render(
            <WhatsAppQRCredentialForm
                credentialType="whatsapp_qr"
                onCredentialCreated={() => {}}
                sendEvent={send as never}
                autoStart={false}
            />,
        );
        const button = screen.getByRole('button', { name: /connect a different whatsapp number/i });
        expect(send).not.toHaveBeenCalled();
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();

        fireEvent.click(button);
        await waitFor(() => expect(send).toHaveBeenCalledWith({ event_name: 'whatsapp:qr:start' }));
        expect(await screen.findByAltText('WhatsApp QR Code')).toBeTruthy();
    });

    // A reconnect restarts the dead session at WAHooks, which logs the phone out: a short blip the health check
    // would have recovered becomes a forced re-scan. Only the user's click may start one.
    it('never auto-starts a reconnect: it idles behind Reconnect WhatsApp until clicked', async () => {
        const send = transport();
        const props = { credentialType: 'whatsapp_qr', onCredentialCreated: () => {}, sendEvent: send as never, reconnectCredentialId: 'cred-1' };
        const { rerender } = render(<WhatsAppQRCredentialForm {...props} autoStart />);
        rerender(<WhatsAppQRCredentialForm {...props} autoStart={false} />);
        rerender(<WhatsAppQRCredentialForm {...props} autoStart />);
        const button = screen.getByRole('button', { name: 'Reconnect WhatsApp' });
        expect(screen.getByText('Shows a new QR code to scan with the same phone.')).toBeTruthy();
        expect(send).not.toHaveBeenCalled();

        fireEvent.click(button);
        await waitFor(() =>
            expect(send).toHaveBeenCalledWith({ event_name: 'whatsapp:qr:start', reconnect_credential_id: 'cred-1' }),
        );
        expect(await screen.findByAltText('WhatsApp QR Code')).toBeTruthy();
    });

    // Linking makes the credential alone: the scan's poll names the connection and nothing else, wherever it's linked
    // (the Connect dialog offers the number an agent after, on its own).
    it('polls the scan for the connection alone', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            const send = transport();
            render(<WhatsAppQRCredentialForm credentialType="whatsapp_qr" onCredentialCreated={() => {}} sendEvent={send as never} />);
            await screen.findByAltText('WhatsApp QR Code');
            await vi.advanceTimersByTimeAsync(5000);
            expect(send).toHaveBeenLastCalledWith({ event_name: 'whatsapp:qr:status', connection_id: 'conn-1' });
        } finally {
            vi.useRealTimers();
        }
    });

    it('asks for the instance WAHooks key in place when the backend reports it missing', async () => {
        const send = vi.fn().mockResolvedValue({ success: false, code: 'wahooks_key_missing', message: 'no key' });
        render(<WhatsAppQRCredentialForm credentialType="whatsapp_qr" onCredentialCreated={() => {}} sendEvent={send as never} />);
        await screen.findByTestId('instance-key-prompt');
        expect(screen.getByRole('button', { name: /Save and show QR/i })).toBeTruthy();
        expect(screen.queryByText(/Retry/)).toBeNull();
    });

    it('waits on the socket as long as the backend waits for a QR', async () => {
        // The backend may wait about a minute for WhatsApp's linking service; the socket's 30s default gave up first.
        socketSend.mockResolvedValue({ success: true, connection_id: 'c', qr_code: 'QR' });
        render(<WhatsAppQRCredentialForm credentialType="whatsapp_qr" onCredentialCreated={() => {}} />);
        await waitFor(() => expect(socketSend).toHaveBeenCalledWith({ event_name: 'whatsapp:qr:start' }, undefined, 90_000));
    });
});
