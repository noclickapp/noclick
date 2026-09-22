import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { LoaderFunctionArgs } from 'react-router';

vi.mock('~/lib/instanceOAuth.server', () => ({ applyInstanceOAuthEnv: vi.fn() }));

import { loader } from '~/routes/api/auth/tiktok.authorize';

beforeEach(() => {
    vi.stubEnv('SESSION_SECRET', 'synthetic-oauth-secret-for-tests-only');
    vi.stubEnv('TIKTOK_CLIENT_KEY', 'test-client-key');
    vi.stubEnv('TIKTOK_REDIRECT_URI', 'https://app.example.com/api/auth/tiktok/callback');
    vi.stubEnv('VITE_PUBLIC_URL', 'https://app.example.com');
});

afterEach(() => vi.unstubAllEnvs());

it('shows TikTok account selection and consent even when a grant already exists', async () => {
    const request = new Request(
        'https://app.example.com/api/auth/tiktok/authorize?name=Test+creator&scopes=user.info.basic%2Cvideo.publish'
    );
    const response = await loader({ request, params: {}, context: {} } as LoaderFunctionArgs);
    const location = new URL(response.headers.get('Location')!);

    expect(location.origin).toBe('https://www.tiktok.com');
    expect(location.pathname).toBe('/v2/auth/authorize/');
    expect(location.searchParams.get('disable_auto_auth')).toBe('1');
    expect(location.searchParams.get('scope')).toBe('user.info.basic,video.publish');
    expect(location.searchParams.get('response_type')).toBe('code');
});
