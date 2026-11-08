// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { OAuthConnectForm } from '~/components/credential/OAuthConnectForm';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
afterEach(() => {
    cleanup();
    delete INTEGRATION_METADATA.oauthProviders.example;
    delete INTEGRATION_METADATA.oauthProviders.other;
});

it('collects and validates declared tenant/data-centre inputs through the shared connect form', () => {
    INTEGRATION_METADATA.oauthProviders.example = {
        provider: 'example',
        credentialType: 'example_oauth',
        authorizeUrl: 'https://provider.example/auth',
        clientIdEnv: 'EXAMPLE_ID',
        clientSecretEnv: 'EXAMPLE_SECRET',
        redirectUriEnv: 'EXAMPLE_CALLBACK',
        scopes: ['read'],
        pkce: false,
        authorizeParams: {},
        contextFields: {
            tenant: {
                source: 'input',
                pattern: '[a-z0-9-]+',
                choices: [],
                kind: 'value',
                label: 'Tenant',
                callbackName: null,
            },
            region: {
                source: 'input',
                pattern: null,
                choices: ['us', 'eu'],
                kind: 'value',
                label: 'Data centre',
                callbackName: null,
            },
        },
    };
    const connect = vi.fn();
    const form = render(
        <OAuthConnectForm
            provider="example"
            credentialType="example_oauth"
            displayName="Example"
            scopes={['read']}
            connect={connect}
            isConnecting={false}
            connectingProvider={null}
        />
    );
    fireEvent.click(
        screen.getByRole('button', { name: /Continue with Example/ })
    );
    expect(connect).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Tenant'), {
        target: { value: 'company' },
    });
    fireEvent.change(screen.getByLabelText('Data centre'), {
        target: { value: 'eu' },
    });
    fireEvent.click(
        screen.getByRole('button', { name: /Continue with Example/ })
    );
    expect(connect.mock.calls[0][7]).toEqual({
        tenant: 'company',
        region: 'eu',
    });
    INTEGRATION_METADATA.oauthProviders.other = {
        ...INTEGRATION_METADATA.oauthProviders.example,
        provider: 'other',
        credentialType: 'other_oauth',
        contextFields: {
            host: {
                source: 'input',
                kind: 'host',
                pattern: null,
                choices: ['eu.provider.example'],
                label: 'Host',
                callbackName: null,
            },
        },
    };
    form.rerender(
        <OAuthConnectForm
            provider="other"
            credentialType="other_oauth"
            displayName="Other"
            scopes={['read']}
            connect={connect}
            isConnecting={false}
            connectingProvider={null}
        />
    );
    fireEvent.change(screen.getByLabelText('Host'), {
        target: { value: 'eu.provider.example' },
    });
    fireEvent.click(
        screen.getByRole('button', { name: /Continue with Other/ })
    );
    expect(connect.mock.calls[1][7]).toEqual({ host: 'eu.provider.example' });
});

it('uses the existing DeviceCodePanel with approval and cancellation', () => {
    const check = vi.fn(),
        cancel = vi.fn();
    render(
        <OAuthConnectForm
            provider="example"
            credentialType="example_oauth"
            displayName="Example"
            scopes={[]}
            connect={vi.fn()}
            isConnecting
            connectingProvider="example"
            onCancel={cancel}
            deviceAuthorization={{
                provider: 'example',
                userCode: 'ABCD',
                verificationUrl: 'https://provider.example/activate',
                polling: false,
                check,
            }}
        />
    );
    expect(screen.getByTestId('device-code-panel')).toBeTruthy();
    expect(screen.getByText('ABCD')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'I’ve approved it' }));
    expect(check).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(cancel).toHaveBeenCalledOnce();
});
