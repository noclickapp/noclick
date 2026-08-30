// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const sendEventAsync = vi.fn();
vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: (...args: unknown[]) => sendEventAsync(...args),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { InstanceSmtpForm } = await import(
    '~/components/credential/InstanceSmtpForm'
);
const { instanceKeysStore } = await import('~/lib/instanceKeys');

function fill() {
    fireEvent.change(screen.getByLabelText('SMTP host'), {
        target: { value: 'smtp.example.com' },
    });
    fireEvent.change(screen.getByLabelText('SMTP username'), {
        target: { value: 'mailer' },
    });
    fireEvent.change(screen.getByLabelText('SMTP password'), {
        target: { value: 'hunter2' },
    });
    fireEvent.change(screen.getByLabelText('Sender address'), {
        target: { value: 'NoClick <noclick@example.com>' },
    });
}

describe('InstanceSmtpForm', () => {
    afterEach(cleanup);

    it('sends the server details as one typed request and feeds the instance-key store', async () => {
        sendEventAsync.mockResolvedValueOnce({
            keys: [
                { env_var: 'SMTP_HOST', updated_at: null },
                { env_var: 'FROM_EMAIL', updated_at: null },
            ],
            env_vars: [],
            supported: [],
        });
        const onSaved = vi.fn();
        render(<InstanceSmtpForm onSaved={onSaved} />);
        expect(
            screen.getByRole('button', { name: /Check and save/ })
        ).toHaveProperty('disabled', true);
        fill();
        fireEvent.click(screen.getByRole('button', { name: /Check and save/ }));
        await waitFor(() => expect(onSaved).toHaveBeenCalled());
        const [request] = sendEventAsync.mock.calls[0];
        expect(request).toMatchObject({
            host: 'smtp.example.com',
            port: 587,
            username: 'mailer',
            password: 'hunter2',
            from_email: 'NoClick <noclick@example.com>',
        });
        expect(instanceKeysStore.configured).toEqual(
            expect.arrayContaining(['SMTP_HOST', 'FROM_EMAIL'])
        );
    });

    it('shows the server\u2019s verdict inline when the login is refused', async () => {
        sendEventAsync.mockResolvedValueOnce({
            error: 'smtp.example.com rejected the login: 5.7.8 Authentication credentials invalid',
        });
        render(<InstanceSmtpForm />);
        fill();
        fireEvent.click(screen.getByRole('button', { name: /Check and save/ }));
        expect((await screen.findByRole('alert')).textContent).toContain(
            'rejected the login'
        );
    });
});
