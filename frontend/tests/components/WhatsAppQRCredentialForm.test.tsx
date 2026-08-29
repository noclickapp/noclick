// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WhatsAppQRCredentialForm } from '~/components/workflow/WhatsAppQRCredentialForm';

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

    it('starts a reconnect scan the moment autoStart flips true', async () => {
        const send = transport();
        const { rerender } = render(
            <WhatsAppQRCredentialForm
                credentialType="whatsapp_qr"
                onCredentialCreated={() => {}}
                sendEvent={send as never}
                autoStart={false}
            />,
        );
        expect(send).not.toHaveBeenCalled();
        rerender(
            <WhatsAppQRCredentialForm
                credentialType="whatsapp_qr"
                onCredentialCreated={() => {}}
                sendEvent={send as never}
                autoStart
                reconnectCredentialId="cred-1"
            />,
        );
        await waitFor(() =>
            expect(send).toHaveBeenCalledWith({ event_name: 'whatsapp:qr:start', reconnect_credential_id: 'cred-1' }),
        );
    });
});
