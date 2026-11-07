// @vitest-environment jsdom
import { useOAuthConnect } from '~/hooks/useOAuthConnect';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { createOAuthHook } from '~/hooks/oauth/createOAuthHook';
const exchange = vi.hoisted(() => vi.fn());
vi.mock('~/hooks/oauth/OAuthExchangeContext', () => ({
    useOAuthExchange: () => exchange,
    useOAuthAuthorizeParams: () => ({}), useOAuthSignInStandIn: () => null,
}));
const useGeneric = createOAuthHook({ provider: '', generic: true });
afterEach(() => vi.restoreAllMocks());

it('connects a declared provider through the generic event with its PKCE verifier', async () => {
    const open = vi
        .spyOn(window, 'open')
        .mockReturnValue({ closed: false } as Window);
    exchange.mockResolvedValue({
        success: true,
        credential_id: 'credential',
        credential_name: 'Example',
    });
    const success = vi.fn();
    const { result, unmount } = renderHook(() =>
        useGeneric({ onSuccess: success })
    );
    act(() =>
        result.current.connectWithConfig(
            {
                provider: 'example',
                generic: true,
                authorizePath: '/api/auth/oauth/example/authorize',
                defaultScopes: ['read'],
                scopeDelimiter: ' ',
            },
            'Account'
        )
    );
    expect(open.mock.calls[0][0]).toContain(
        '/api/auth/oauth/example/authorize?'
    );
    await act(async () => {
        window.dispatchEvent(
            new MessageEvent('message', {
                origin: window.location.origin,
                data: {
                    type: 'example-oauth-callback',
                    success: true,
                    code: 'code',
                    redirectUri: 'https://app.example/callback',
                    codeVerifier: 'verifier',
                    scopes: ['read'],
                },
            })
        );
    });
    await waitFor(() => expect(success).toHaveBeenCalled());
    expect(exchange).toHaveBeenCalledWith(
        expect.objectContaining({
            event_name: 'oauth:exchange',
            provider: 'example',
            code: 'code',
            code_verifier: 'verifier',
        })
    );
    expect(result.current.isConnecting).toBe(false);
    unmount();
});


it('useOAuthConnect dispatches metadata-only providers without a hook map entry', async () => {
    exchange.mockResolvedValue({ success: true, credential_id: 'credential', credential_name: 'Example' });
    INTEGRATION_METADATA.oauthProviders.example = { provider: 'example', authorizeUrl: 'https://example.com/authorize', scopes: ['read'], pkce: true, clientIdEnv: 'EXAMPLE_ID', redirectUriEnv: 'EXAMPLE_REDIRECT', authorizeParams: {}, credentialType: 'example_oauth' };
    vi.spyOn(window, 'open').mockReturnValue({ closed: false } as Window);
    const created = vi.fn();
    const { result, unmount } = renderHook(() => useOAuthConnect({ onCredentialCreated: created }));
    act(() => result.current.connect('example', 'Example'));
    expect(result.current.connectingProvider).toBe('example');
    await act(async () => {
        window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin, data: { type: 'example-oauth-callback', success: true, code: 'code', redirectUri: 'https://app.example/callback' } }));
    });
    await waitFor(() => expect(created).toHaveBeenCalledWith('credential', 'example', undefined));
    expect(result.current.isConnecting).toBe(false);
    unmount();
    delete INTEGRATION_METADATA.oauthProviders.example;
});
