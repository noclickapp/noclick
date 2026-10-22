// Phone purchase actions forward verified session identity and require CSRF.
// These tests exercise the actual route handlers, including cookie refresh and
// return-link restrictions, without calling the phone provider. The operations
// live on their own route: a page route answers a POST with its HTML, which the
// page's purchase form and the chat's number card both tried to read as JSON.
import { afterEach, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => vi.fn());
vi.mock('~/lib/supabase', () => ({ requireAuth: auth }));
vi.mock('~/lib/serverSecrets', () => ({ getServerSecret: () => 'test-only-csrf-secret' }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
import * as page from '~/routes/credential.purchase.$token';
import { action } from '~/routes/credential.purchase.$token.action';
import { generateCsrfToken } from '~/lib/csrf.server';
import { createStaticHandler } from 'react-router';

const { loader } = page;

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

function signIn() {
    auth.mockResolvedValue({ session: { access_token: 'verified-session' }, backendHeaders: { Authorization: 'Bearer verified-session' }, user: { email: 'owner@example.com' }, headers: new Headers({ 'Set-Cookie': 'auth=rotated; Path=/' }) });
    vi.stubEnv('VITE_API_URL', 'https://backend.example');
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
    expect(((await response.json()) as { csrfToken?: string }).csrfToken).toBeTruthy();
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

it('a backend error page reads as a failed request, not a crash', async () => {
    signIn().mockResolvedValue(new Response('<!DOCTYPE html><title>502</title>', { status: 502 }));
    const response = await loader({ request: new Request('https://app.example/credential/purchase/token'), params: { token: 'token' } } as never);
    expect((await response.json()).purchase).toEqual({ error: 'Could not complete this request (502).' });
});

it('answers its operations as JSON, which the page route never could', async () => {
    // What the server does with each: a page route turns an action's JSON into page data for its HTML; the
    // operations route returns the action's own Response.
    signIn();
    const pageRoute = { id: 'page', path: '/credential/purchase/:token', loader: () => ({}), action: () => new Response('{}'), Component: () => null };
    const handler = createStaticHandler([pageRoute, { id: 'operations', path: '/credential/purchase/:token/action', action }]);
    expect(await handler.query(new Request('https://app.example/credential/purchase/token', { method: 'POST', body: new FormData() }))).not.toBeInstanceOf(Response);
    const url = 'https://app.example/credential/purchase/token/action';
    const csrf = await generateCsrfToken(new Request(url));
    const form = new FormData(); form.set('csrf_token', csrf.token); form.set('operation', 'search'); form.set('payload', '{}');
    const reply = await handler.queryRoute(new Request(url, { method: 'POST', headers: { Cookie: csrf.cookieHeader.split(';')[0] }, body: form }));
    expect(reply).toBeInstanceOf(Response);
    expect((reply as Response).headers.get('Content-Type')).toContain('application/json');
    expect('action' in page).toBe(false);
});
