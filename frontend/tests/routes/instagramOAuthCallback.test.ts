// Exercise actual authorize/callback loaders with synthetic browser bindings.
// Invalid state must remain rejected without stranding users on a generic 400.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/instanceOAuth.server', () => ({
    applyInstanceOAuthEnv: vi.fn(),
}));
import { loader as authorize } from '~/routes/api/auth/instagram.authorize';
import { loader as callback } from '~/routes/api/auth/instagram.callback';
import type { LoaderFunctionArgs } from 'react-router';

const attempt = '12345678-1234-1234-1234-123456789abc';
const args = (request: Request) =>
    ({ request, params: {}, context: {} }) as LoaderFunctionArgs;
async function begin() {
    const response = await authorize(
        args(
            new Request(
                `https://app.example.com/api/auth/instagram/authorize?callback_channel=${attempt}`
            )
        )
    );
    const target = new URL(response.headers.get('Location')!);
    return {
        cookie: response.headers.get('Set-Cookie')!.split(';')[0],
        state: target.searchParams.get('state')!,
    };
}
function request(
    state: string,
    cookie?: string,
    origin = 'https://app.example.com',
    result = 'code=synthetic-code'
) {
    return args(
        new Request(
            `${origin}/api/auth/instagram/callback?${result}&state=${state}`,
            { headers: cookie ? { Cookie: cookie } : {} }
        )
    );
}

describe('Instagram OAuth callback validation', () => {
    beforeEach(() => {
        vi.stubEnv('SESSION_SECRET', 'synthetic-oauth-secret-for-tests-only');
        vi.stubEnv('INSTAGRAM_APP_ID', 'test-app');
        vi.stubEnv(
            'INSTAGRAM_REDIRECT_URI',
            'https://callback.example.com/api/auth/instagram/callback'
        );
        vi.stubEnv('VITE_PUBLIC_URL', 'https://app.example.com');
    });
    afterEach(() => {
        vi.unstubAllEnvs();
    });

    it('restores the attempt channel only after validating the binding', async () => {
        const flow = await begin();
        const result = await callback(request(flow.state, flow.cookie));
        expect(result).toMatchObject({
            success: true,
            callbackChannel: attempt,
            code: 'synthetic-code',
        });
        expect(flow.state).not.toContain(attempt);
    });
    it('bounces encrypted state to the trusted originating app before delivery', async () => {
        const flow = await begin();
        try {
            await callback(
                request(flow.state, undefined, 'https://callback.example.com')
            );
            expect.unreachable('must redirect to the bound origin');
        } catch (response) {
            expect(response).toBeInstanceOf(Response);
            const location = new URL(
                (response as Response).headers.get('Location')!
            );
            expect(location.origin).toBe('https://app.example.com');
            expect(location.searchParams.get('state')).toBe(flow.state);
            expect(
                (
                    await callback(
                        args(
                            new Request(location, {
                                headers: { Cookie: flow.cookie },
                            })
                        )
                    )
                ).success
            ).toBe(true);
        }
    });
    it('does not release code or channel without a browser binding', async () => {
        const flow = await begin();
        const result = await callback(request(flow.state));
        expect(result.success).toBe(false);
        expect(result.code).toBeUndefined();
        expect(result.callbackChannel).toBeUndefined();
        expect(result.error).toContain('could not be verified');
    });
    it('turns invalid or missing state into actionable failure, never exchange data', async () => {
        for (const state of ['invalid', '']) {
            const result = await callback(request(state));
            expect(result.success).toBe(false);
            expect(result.code).toBeUndefined();
            expect(result.error).toContain('start Connect Instagram again');
        }
    });
    it('delivers a provider decline on the validated attempt without a code', async () => {
        const flow = await begin();
        const result = await callback(
            request(
                flow.state,
                flow.cookie,
                'https://app.example.com',
                'error=access_denied&error_description=Permission+declined'
            )
        );
        expect(result).toEqual({
            success: false,
            callbackChannel: attempt,
            error: 'Permission declined',
        });
    });
    it('rejects a malformed callback-channel input before redirecting', async () => {
        await expect(
            authorize(
                args(
                    new Request(
                        'https://app.example.com/api/auth/instagram/authorize?callback_channel=shared'
                    )
                )
            )
        ).rejects.toMatchObject({ status: 400 });
    });
});
