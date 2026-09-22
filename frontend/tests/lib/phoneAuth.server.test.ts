// The login page's phone sign-in (authenticate 'phone_send' / 'phone_verify'):
// the captcha gates the SMS, the backend's prepare step picks the number's
// canonical form (and account) before Supabase sends the code, and a verified
// sign-in reports back so the number binds to the account it signed into.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const auth = {
    signInWithOtp: vi.fn(),
    verifyOtp: vi.fn(),
};
vi.mock('~/lib/supabase', () => ({
    createServerSupabaseClient: () => ({ auth }),
}));
vi.mock('~/lib/hostedDefaults', () => ({ apiBaseUrl: () => 'https://api.test' }));

import { authenticate } from '~/lib/auth.server';

const request = new Request('https://app.test/auth/login', { method: 'POST' });
const fetchMock = vi.fn();

beforeEach(() => {
    vi.stubEnv('VITE_DISABLE_CAPTCHA', 'true');
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    auth.signInWithOtp.mockReset();
    auth.verifyOtp.mockReset();
});
afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
});

describe('phone sign-in', () => {
    it('prepares the number with the backend, then asks Supabase to text a code', async () => {
        fetchMock.mockResolvedValue(new Response(JSON.stringify({ phone: '+14242421064' }), { status: 200 }));
        auth.signInWithOtp.mockResolvedValue({ error: null });
        const result = await authenticate(request, 'phone_send', { phone: '+1 (424) 242-1064' });
        expect(result.error).toBeUndefined();
        expect(result.phone).toBe('+14242421064');
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe('https://api.test/api/auth/phone/prepare');
        expect(JSON.parse(init.body)).toEqual({ phone: '+1 (424) 242-1064' });
        // The canonical number goes to Supabase; a first sign-in names the account by it, masked.
        expect(auth.signInWithOtp).toHaveBeenCalledWith({
            phone: '+14242421064',
            options: { data: { username: '+1••••••1064', signup_channel: 'phone' } },
        });
    });

    it('stops before any SMS when the backend refuses the number', async () => {
        fetchMock.mockResolvedValue(
            new Response(JSON.stringify({ detail: { error: 'Enter the full number with its country code', kind: 'invalid_number' } }), {
                status: 400,
            })
        );
        const result = await authenticate(request, 'phone_send', { phone: '4242421064' });
        expect(result.error).toBe('Enter the full number with its country code');
        expect(auth.signInWithOtp).not.toHaveBeenCalled();
    });

    it('needs the captcha before it spends an SMS', async () => {
        vi.stubEnv('VITE_DISABLE_CAPTCHA', 'false');
        const result = await authenticate(request, 'phone_send', { phone: '+14242421064' });
        expect(result.error).toBe('CAPTCHA verification required');
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('verifies the code and binds the number to the signed-in account', async () => {
        auth.verifyOtp.mockResolvedValue({ data: { session: { access_token: 'jwt' } }, error: null });
        fetchMock.mockResolvedValue(new Response(JSON.stringify({ phone: '+14242421064' }), { status: 200 }));
        const result = await authenticate(request, 'phone_verify', { phone: '+14242421064', code: '123 456' });
        expect(result.error).toBeUndefined();
        expect(auth.verifyOtp).toHaveBeenCalledWith({ phone: '+14242421064', token: '123456', type: 'sms' });
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe('https://api.test/api/auth/phone/confirmed');
        expect(init.headers.Authorization).toBe('Bearer jwt');
    });

    it('keeps the code step open on a wrong code', async () => {
        auth.verifyOtp.mockResolvedValue({ data: { session: null }, error: { message: 'Token has expired or is invalid' } });
        const result = await authenticate(request, 'phone_verify', { phone: '+14242421064', code: '000000' });
        expect(result.error).toBe("That code isn't right or has expired.");
        expect(result.phone).toBe('+14242421064');
        expect(fetchMock).not.toHaveBeenCalled();
    });
});
