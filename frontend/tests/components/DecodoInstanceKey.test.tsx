// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const send = vi.fn();
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: (...args: unknown[]) => send(...args) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('~/components/credential/InstanceSmtpForm', () => ({ InstanceSmtpForm: () => null }));
vi.mock('~/lib/instanceKeys', () => ({
    loadInstanceKeys: async () => ({ keys: [], env_vars: [], supported: ['DECODO_AUTH_TOKEN'] }),
    applyInstanceKeysState: vi.fn(),
}));

const { InstanceProviderKeysSettings } = await import('~/components/settings/InstanceProviderKeysSettings');
afterEach(cleanup);

it('lets a self-hosted operator configure the Decodo token used by Reddit', async () => {
    send.mockResolvedValueOnce({ keys: [{ env_var: 'DECODO_AUTH_TOKEN' }], env_vars: [], supported: ['DECODO_AUTH_TOKEN'] });
    render(<InstanceProviderKeysSettings />);
    const input = await screen.findByLabelText('DECODO_AUTH_TOKEN value');
    expect(screen.getByText('Reddit scraping')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Get a Decodo key' }).getAttribute('href')).toBe('https://dashboard.decodo.com/playground');
    expect(input.getAttribute('type')).toBe('password');
    fireEvent.change(input, { target: { value: 'example-auth-token' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0][0]).toMatchObject({ env_var: 'DECODO_AUTH_TOKEN', value: 'example-auth-token' });
    await screen.findByRole('button', { name: 'Remove the DECODO_AUTH_TOKEN key' });
});
