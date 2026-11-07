// @vitest-environment happy-dom
// The ways in a shared connect link offers (2026-11-06): only those it can finish, and "It's encrypted as soon as you
// send it" only under what a person types in, never a sign-in, which sends nothing through the page.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('~/components/credential/CredentialMethodConnect', () => ({
    CredentialMethodConnect: ({ method }: { method: { label: string } }) => <div>connect {method.label}</div>,
}));

import { CredentialProvideFlow, type ProvideRequestDetails } from '~/components/credential/CredentialProvideFlow';

const request = (overrides: Partial<ProvideRequestDetails>): ProvideRequestDetails => ({
    credential_type: 'typeform_oauth',
    requester_name: 'NoClick',
    requester_email: null,
    is_oauth: true,
    oauth_provider: 'typeform',
    oauth_scopes: [],
    requires_pkce: false,
    credential_fields: [],
    available_methods: [],
    status: 'pending',
    expires_at: '',
    ...overrides,
});

const NOTE = 'It’s encrypted as soon as you send it.';

afterEach(cleanup);

it('says nothing about encryption under a sign-in', () => {
    render(<CredentialProvideFlow token="t" apiBase="" held={request({})} onProvided={() => {}} />);
    expect(screen.getByText(/connect/)).toBeTruthy();
    expect(screen.queryByText(NOTE)).toBeNull();
});

it('says a typed key is encrypted once sent', () => {
    render(
        <CredentialProvideFlow
            token="t"
            apiBase=""
            held={request({
                credential_type: 'fal_api_key',
                is_oauth: false,
                oauth_provider: undefined,
                credential_fields: [{ name: 'api_key', label: 'API key', type: 'password', required: true }],
            })}
            onProvided={() => {}}
        />
    );
    expect(screen.getByText(NOTE)).toBeTruthy();
});

const method = (credential_type: string, label: string, kind: 'oauth' | 'api_key', oauth_provider?: string) => ({
    credential_type,
    label,
    method_kind: kind,
    is_oauth: kind === 'oauth',
    oauth_provider,
    credential_fields: kind === 'api_key' ? [{ name: 'access_token', label: 'Access token', type: 'password', required: true }] : [],
});

it('leaves out a sign-in a shared link cannot finish', () => {
    render(
        <CredentialProvideFlow
            token="t"
            apiBase=""
            held={request({
                credential_type: 'instagram_login',
                oauth_provider: 'instagram_login',
                available_methods: [
                    method('instagram_login', 'InstagramLogin', 'oauth', 'instagram_login'),
                    // Picks the Instagram account after Facebook's popup: only the app's own form can.
                    method('instagram_oauth', 'Instagram with Facebook Login', 'oauth', 'facebook'),
                    method('instagram_page_access_token', 'InstagramPageAccessToken', 'api_key'),
                ],
            })}
            onProvided={() => {}}
        />
    );
    expect(screen.getByText('connect Instagram Login')).toBeTruthy();
    expect(screen.queryByText(/Facebook Login/)).toBeNull();
});

it('still shows such a sign-in when it is the only way in, so the page can say why', () => {
    render(
        <CredentialProvideFlow
            token="t"
            apiBase=""
            held={request({
                credential_type: 'instagram_oauth',
                oauth_provider: 'facebook',
                available_methods: [method('instagram_oauth', 'Instagram with Facebook Login', 'oauth', 'facebook')],
            })}
            onProvided={() => {}}
        />
    );
    expect(screen.getByText('connect Instagram with Facebook Login')).toBeTruthy();
});
