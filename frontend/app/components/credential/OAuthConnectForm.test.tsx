// @vitest-environment jsdom
// Pins the shared OAuth connect mechanisms so a provider that needs a pre-connect input
// can't work in one surface and silently break the other (the Shopify-on-the-link gap).
// Both the in-app credential UI and the public provide link render THIS component, so these
// assertions cover both at once: the tenant/BYOO inputs appear, normalize, and land in the
// right positional connect() arg.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import {
    OAuthConnectForm,
    resolveOAuthRedirectUri,
    type OAuthConnectFormProps,
} from './OAuthConnectForm';

afterEach(cleanup); // no global setup file → unmount between tests ourselves

const base = { connectingProvider: null, isConnecting: false, Icon: () => null } as const;

function renderForm(props: Partial<OAuthConnectFormProps>) {
    const connect = vi.fn();
    render(<OAuthConnectForm {...({ ...base, connect, ...props } as OAuthConnectFormProps)} />);
    return connect;
}

describe('OAuthConnectForm — shared connect mechanisms', () => {
    it('resolves schema callback paths against this installation and preserves absolute URLs', () => {
        expect(
            resolveOAuthRedirectUri(
                '/api/auth/intuit/callback',
                'https://self-hosted.example/'
            )
        ).toBe('https://self-hosted.example/api/auth/intuit/callback');
        expect(
            resolveOAuthRedirectUri(
                'https://oauth-proxy.example/callback',
                'https://self-hosted.example'
            )
        ).toBe('https://oauth-proxy.example/callback');
    });

    it('shopify requires a store name and passes the normalized shop (4th arg)', () => {
        const connect = renderForm({ provider: 'shopify', credentialType: 'shopify_oauth', displayName: 'Shopify', scopes: ['read_products'] });
        expect(screen.getByText('.myshopify.com')).toBeTruthy();
        const btn = screen.getByRole('button', { name: /Connect Shopify Account/i }) as HTMLButtonElement;
        expect(btn.disabled).toBe(true); // no shop yet
        fireEvent.change(screen.getByPlaceholderText('my-store'), { target: { value: 'https://My-Store.myshopify.com/admin' } });
        expect(btn.disabled).toBe(false);
        fireEvent.click(btn);
        expect(connect).toHaveBeenCalledTimes(1);
        const args = connect.mock.calls[0];
        expect(args[0]).toBe('shopify');
        expect(args[3]).toBe('my-store'); // normalized shop
    });

    it('atlassian passes the site as the 5th arg', () => {
        const connect = renderForm({ provider: 'atlassian', credentialType: 'jira_oauth', displayName: 'Jira', scopes: ['read:jira-work'] });
        fireEvent.change(screen.getByPlaceholderText('your-company'), { target: { value: 'acme.atlassian.net' } });
        fireEvent.click(screen.getByRole('button', { name: /Connect Jira Account/i }));
        expect(connect.mock.calls[0][4]).toBe('acme');
    });

    it('a plain provider (linear) has no tenant input and connects immediately', () => {
        const connect = renderForm({ provider: 'linear', credentialType: 'linear_oauth', displayName: 'Linear', scopes: ['read'] });
        expect(screen.queryByText('.myshopify.com')).toBeNull();
        const btn = screen.getByRole('button', { name: /Connect Linear Account/i }) as HTMLButtonElement;
        expect(btn.disabled).toBe(false);
        fireEvent.click(btn);
        expect(connect).toHaveBeenCalledWith('linear', expect.any(String), ['read'], undefined, undefined, undefined, undefined);
    });

    it('BYOO (requiresCustomClient) blocks connect until client id + secret, then passes them (7th arg)', () => {
        const connect = renderForm({ provider: 'google', credentialType: 'google_business_profile_oauth', displayName: 'Google', scopes: ['x'], requiresCustomClient: true, redirectUri: '/api/auth/google/callback' });
        expect(screen.getByText(`${window.location.origin}/api/auth/google/callback`)).toBeTruthy();
        const btn = screen.getByRole('button', { name: /Connect Google Account/i }) as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
        fireEvent.change(screen.getByPlaceholderText(/apps\.googleusercontent\.com/), { target: { value: 'cid' } });
        fireEvent.change(screen.getByPlaceholderText('GOCSPX-...'), { target: { value: 'sec' } });
        expect(btn.disabled).toBe(false);
        fireEvent.click(btn);
        expect(connect.mock.calls[0][6]).toEqual({ client_id: 'cid', client_secret: 'sec' });
    });
});
