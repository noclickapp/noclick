// Phone purchase actions forward verified session identity and require CSRF.
// These tests exercise the actual route handlers, including cookie refresh and
// return-link restrictions, without calling the phone provider.
import { afterEach, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => vi.fn());
vi.mock('~/lib/supabase', () => ({ requireAuth: auth }));
vi.mock('~/lib/serverSecrets', () => ({ getServerSecret: () => 'test-only-csrf-secret' }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
import { action, loader } from '~/routes/credential.purchase.$token';
import { generateCsrfToken } from '~/lib/csrf.server';

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

function signIn() {
    auth.mockResolvedValue({ session: { access_token: 'verified-session' }, user: { email: 'owner@example.com' }, headers: new Headers({ 'Set-Cookie': 'auth=rotated; Path=/' }) });
    vi.stubEnv('API_URL', 'https://backend.example');
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'pending', purpose: 'Receptionist' }), { headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetcher);
    return fetcher;
}

it('requires sign-in before reading the purchase', async () => {
    const fetcher = signIn();
    const redirect = new Response(null, { status: 302, headers: { Location: '/auth/login' } });
    auth.mockRejectedValue(redirect);
    await expect(loader({ request: new Request('https://app.example/credential/purchase/token'), params: { token: 'token' } } as never)).rejects.toBe(redirect);
    expect(fetcher).not.toHaveBeenCalled();
});

it('reads with verified identity and private cache headers, rejecting external return URLs', async () => {
    const fetcher = signIn();
    const response = await loader({ request: new Request('https://app.example/credential/purchase/token?return_to=//evil.example'), params: { token: 'token' } } as never);
    expect((await response.json()).returnTo).toBe('/dashboard?tab=dashboard');
    expect(response.headers.get('Cache-Control')).toContain('no-store');
    expect(response.headers.get('Referrer-Policy')).toBe('no-referrer');
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer verified-session');
    expect(response.headers.get('Set-Cookie')).toContain('auth=rotated');
});

it('refuses missing CSRF without forwarding a purchase and preserves refreshed auth', async () => {
    const fetcher = signIn();
    const form = new FormData(); form.set('operation', 'confirm');
    const response = await action({ request: new Request('https://app.example/credential/purchase/token', { method: 'POST', body: form }), params: { token: 'token' } } as never);
    expect(response.status).toBe(400);
    expect((await response.json()).csrfToken).toBeTruthy();
    expect(response.headers.get('Set-Cookie')).toContain('auth=rotated');
    expect(fetcher).not.toHaveBeenCalled();
});

it('forwards an explicit confirmed quote only after a valid CSRF submission', async () => {
    const fetcher = signIn();
    const url = 'https://app.example/credential/purchase/token';
    const csrf = await generateCsrfToken(new Request(url));
    const form = new FormData(); form.set('csrf_token', csrf.token); form.set('operation', 'confirm'); form.set('payload', JSON.stringify({ quote_id: 'server-quote' }));
    const response = await action({ request: new Request(url, { method: 'POST', headers: { Cookie: csrf.cookieHeader.split(';')[0] }, body: form }), params: { token: 'token' } } as never);
    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledWith('https://backend.example/api/credential-request/token/phone/confirm', expect.objectContaining({ body: '{"quote_id":"server-quote"}', headers: expect.objectContaining({ Authorization: 'Bearer verified-session' }) }));
});
