// Security boundary: a logged-in agent-visible link is not a mutation token.
import { afterEach, expect, it, vi } from 'vitest';
import { submitCredentialReview } from './credentialReview.server';
const auth = vi.hoisted(() => vi.fn());
const csrf = vi.hoisted(() => vi.fn());
vi.mock('~/lib/supabase', () => ({ requireAuth: auth }));
vi.mock('~/lib/csrf.server', () => ({ csrfFailureResponse: csrf, generateCsrfToken: vi.fn() }));
afterEach(() => vi.unstubAllGlobals());

it('rejects a forged form before any backend decision call and preserves rotated session cookies', async () => {
    auth.mockResolvedValue({ session: { access_token: 'browser-session' }, headers: new Headers({ 'Set-Cookie': 'rotated-session=test' }) });
    csrf.mockResolvedValue(new Response('Invalid CSRF token', { status: 403 }));
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const form = new FormData();
    form.set('payload', JSON.stringify({ decision: 'approved' }));
    const response = await submitCredentialReview(new Request('https://app.test/credential/approval/request', { method: 'POST', body: form }), 'approval/request');
    expect(response.status).toBe(403);
    expect(response.headers.get('Set-Cookie')).toBe('rotated-session=test');
    expect(fetch).not.toHaveBeenCalled();
});
