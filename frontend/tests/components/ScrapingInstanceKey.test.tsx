// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const send = vi.fn();
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: (...args: unknown[]) => send(...args) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('~/components/credential/InstanceSmtpForm', () => ({ InstanceSmtpForm: () => null }));
vi.mock('~/lib/instanceKeys', () => ({
    loadInstanceKeys: async () => ({ keys: [], env_vars: [], supported: ['APIFY_API_TOKEN'] }),
    applyInstanceKeysState: vi.fn(),
}));

const { InstanceProviderKeysSettings } = await import('~/components/settings/InstanceProviderKeysSettings');
afterEach(cleanup);

it('lets a self-hosted operator configure the Apify token Reddit, LinkedIn and Instagram scraping run on', async () => {
    send.mockResolvedValueOnce({ keys: [{ env_var: 'APIFY_API_TOKEN' }], env_vars: [], supported: ['APIFY_API_TOKEN'] });
    render(<InstanceProviderKeysSettings />);
    const input = await screen.findByLabelText('APIFY_API_TOKEN value');
    expect(screen.getByText('Reddit, LinkedIn and Instagram scraping')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Get an Apify key' }).getAttribute('href')).toBe('https://console.apify.com/settings/integrations');
    expect(input.getAttribute('type')).toBe('password');
    fireEvent.change(input, { target: { value: 'example-auth-token' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0][0]).toMatchObject({ env_var: 'APIFY_API_TOKEN', value: 'example-auth-token' });
    await screen.findByRole('button', { name: 'Remove the APIFY_API_TOKEN key' });
});
