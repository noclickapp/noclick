// Verify the real Facebook authorize loader requests business Page access.
// The browser credential schema and route defaults must agree, otherwise
// business-owned Instagram accounts silently disappear from Meta's Page list.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { LoaderFunctionArgs } from 'react-router';
import instagramSchema from '../../app/schemas/nodes/instagram.json';

vi.mock('~/lib/instanceOAuth.server', () => ({ applyInstanceOAuthEnv: vi.fn() }));

import { loader } from '~/routes/api/auth/facebook.authorize';

beforeEach(() => {
    vi.stubEnv('SESSION_SECRET', 'synthetic-oauth-secret-for-tests-only');
    vi.stubEnv('FACEBOOK_APP_ID', 'test-app');
    vi.stubEnv('FACEBOOK_OAUTH_REDIRECT_URI', 'https://app.example.com/api/auth/facebook/callback');
    vi.stubEnv('VITE_PUBLIC_URL', 'https://app.example.com');
});
afterEach(() => vi.unstubAllEnvs());

async function authorize(scopes?: string[]) {
    const request = new Request(`https://app.example.com/api/auth/facebook/authorize${
        scopes ? `?scopes=${encodeURIComponent(scopes.join(','))}` : ''
    }`);
    const response = await loader({ request, params: {}, context: {} } as LoaderFunctionArgs);
    return new URL(response.headers.get('Location')!);
}

it('requests business discovery and IG User permissions from both connection entry points', async () => {
    const schemaScopes = instagramSchema.$defs.InstagramOAuthCredential['x-oauth-scopes'];
    expect(schemaScopes).toEqual(expect.arrayContaining(['business_management', 'ads_read']));
    expect(schemaScopes).not.toContain('ads_management');
    for (const requested of [undefined, schemaScopes]) {
        const url = await authorize(requested);
        expect(url.searchParams.get('scope')!.split(',').sort()).toEqual([...schemaScopes].sort());
        expect(url.searchParams.get('auth_type')).toBe('rerequest');
        expect(url.searchParams.get('response_type')).toBe('code');
    }
});

it('preserves explicit scopes for the shared Facebook Pages connection', async () => {
    const scopes = ['pages_show_list', 'pages_manage_posts'];
    expect((await authorize(scopes)).searchParams.get('scope')).toBe(scopes.join(','));
});
