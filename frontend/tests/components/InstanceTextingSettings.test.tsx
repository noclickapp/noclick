// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from '@testing-library/react';
import type { InstanceKeysState } from '~/lib/instanceKeys';

const send = vi.fn();
vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: (...args: unknown[]) => send(...args),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('~/lib/instanceKeys', () => ({ applyInstanceKeysState: vi.fn() }));

const { InstanceTextingSettings } = await import(
    '~/components/settings/InstanceTextingSettings'
);
afterEach(() => {
    cleanup();
    send.mockReset();
});

const app = (overrides = {}) => ({
    configured: false,
    line: null,
    webhook_url: 'https://chat.example.org/whatsapp/meta',
    app_url: 'https://chat.example.org',
    redis: true,
    ...overrides,
});
const state = (texting = {}): InstanceKeysState => ({
    keys: [],
    env_vars: [],
    supported: [],
    texting: {
        whatsapp: app(),
        imessage: app({
            webhook_url: 'https://chat.example.org/imessage/sendblue',
        }),
        ...texting,
    },
});

it('saves WhatsApp keys together, then shows the URL and the verify token to paste into Meta', async () => {
    const saved: InstanceKeysState = {
        ...state({ whatsapp: app({ configured: true, line: '+15550100000' }) }),
        keys: [{ env_var: 'WHATSAPP_CLOUD_API_TOKEN', updated_at: null }],
    };
    send.mockResolvedValueOnce({
        ...saved,
        made: { WHATSAPP_WEBHOOK_VERIFY_TOKEN: 'made-once-token' },
    });
    let current = state();
    const { rerender } = render(
        <InstanceTextingSettings
            state={current}
            onChange={(s) => (current = s)}
        />
    );
    const row = within(screen.getByTestId('texting-whatsapp'));
    const save = row.getByRole('button', { name: 'Check and save' });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(row.getByLabelText('Phone number ID'), {
        target: { value: '100000000000001' },
    });
    fireEvent.change(row.getByLabelText('Access token'), {
        target: { value: 'EAAG-token' },
    });
    expect(row.getByLabelText('Access token').getAttribute('type')).toBe(
        'password'
    );
    fireEvent.change(row.getByLabelText('App secret'), {
        target: { value: 'app-secret' },
    });
    fireEvent.submit(save.closest('form')!);
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0][0]).toMatchObject({
        app: 'whatsapp',
        fields: {
            WHATSAPP_PHONE_NUMBER_ID: '100000000000001',
            WHATSAPP_CLOUD_API_TOKEN: 'EAAG-token',
            WHATSAPP_APP_SECRET: 'app-secret',
        },
    });
    rerender(
        <InstanceTextingSettings
            state={current}
            onChange={(s) => (current = s)}
        />
    );
    const configured = within(screen.getByTestId('texting-whatsapp'));
    await configured.findByText(/Answering on/);
    expect(
        configured.getByText('https://chat.example.org/whatsapp/meta')
    ).toBeTruthy();
    expect(configured.getByText('made-once-token')).toBeTruthy();
});

it('says what a refused key is wrong with, and keeps the form', async () => {
    send.mockResolvedValueOnce({
        error: 'Sendblue refused the keys: Invalid API key',
    });
    render(
        <InstanceTextingSettings state={state()} onChange={() => undefined} />
    );
    const row = within(screen.getByTestId('texting-imessage'));
    fireEvent.change(row.getByLabelText('Line'), {
        target: { value: '+1 415 555 0123' },
    });
    fireEvent.change(row.getByLabelText('API key'), { target: { value: 'k' } });
    fireEvent.change(row.getByLabelText('API secret'), {
        target: { value: 's' },
    });
    fireEvent.submit(
        row.getByRole('button', { name: 'Check and save' }).closest('form')!
    );
    expect((await row.findByRole('alert')).textContent).toBe(
        'Sendblue refused the keys: Invalid API key'
    );
    expect(row.getByLabelText('Line')).toBeTruthy();
});

it('says texting needs Redis and a public HTTPS address when the instance has neither', () => {
    render(
        <InstanceTextingSettings
            state={state({
                whatsapp: app({
                    redis: false,
                    webhook_url: 'http://localhost:8000/whatsapp/meta',
                }),
            })}
            onChange={() => undefined}
        />
    );
    expect(screen.getByText(/Texting needs Redis/)).toBeTruthy();
    expect(screen.getByText(/has to be a public HTTPS address/)).toBeTruthy();
});

it('removes every key of an app together', async () => {
    const configured: InstanceKeysState = {
        ...state({ imessage: app({ configured: true, line: '+14155550123' }) }),
        keys: [
            'SENDBLUE_API_KEY',
            'SENDBLUE_API_SECRET',
            'SENDBLUE_NUMBER',
            'SENDBLUE_WEBHOOK_SECRET',
        ].map((env_var) => ({ env_var, updated_at: null })),
    };
    send.mockResolvedValue(state());
    render(
        <InstanceTextingSettings
            state={configured}
            onChange={() => undefined}
        />
    );
    fireEvent.click(
        within(screen.getByTestId('texting-imessage')).getByRole('button', {
            name: 'Remove iMessage',
        })
    );
    await waitFor(() => expect(send).toHaveBeenCalledTimes(4));
    expect(send.mock.calls.map((c) => c[0].env_var)).toEqual([
        'SENDBLUE_API_KEY',
        'SENDBLUE_API_SECRET',
        'SENDBLUE_NUMBER',
        'SENDBLUE_WEBHOOK_SECRET',
    ]);
});

it('says where the links it texts open while a phone can’t reach the app', () => {
    render(
        <InstanceTextingSettings
            state={state({
                whatsapp: app({ app_url: 'http://127.0.0.1:3000' }),
            })}
            onChange={() => {}}
        />
    );
    expect(screen.getByText(/Links it texts/).textContent).toContain(
        'http://127.0.0.1:3000'
    );
    cleanup();
    render(<InstanceTextingSettings state={state()} onChange={() => {}} />);
    expect(screen.queryByText(/Links it texts/)).toBeNull();
});
