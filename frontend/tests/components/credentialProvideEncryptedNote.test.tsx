// @vitest-environment jsdom
// A connect link's "It's encrypted as soon as you send it" belongs to what a person types in: a sign-in sends nothing
// through the page, and under its button the line read as a promise about nothing (2026-11-06).
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
