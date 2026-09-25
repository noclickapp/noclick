// The credential policy loader also backs the in-canvas approval-rules fetcher
// on every tool-wired node, so a throw here replaced the whole dashboard with the
// error page. It read process.env.API_URL, which the hosted deployment never sets
// (the backend URL is VITE_API_URL), so every load fetched "undefined/api/…".
import { afterEach, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => vi.fn());
vi.mock('~/lib/supabase', () => ({ requireAuth: auth }));
vi.mock('~/lib/serverSecrets', () => ({ getServerSecret: () => 'test-only-csrf-secret' }));
vi.mock('~/components/credential/CredentialPermissions', () => ({ CredentialPermissions: () => null }));
import { loader } from '~/routes/credential.permissions.$credentialId';

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

function signIn(response: Response) {
    auth.mockResolvedValue({ session: { access_token: 'verified-session' }, headers: new Headers() });
    vi.stubEnv('API_URL', '');
    vi.stubEnv('VITE_API_URL', 'https://backend.example');
    const fetcher = vi.fn().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetcher);
    return fetcher;
}

const load = () =>
    loader({ request: new Request('https://app.example/credential/permissions/cred-1'), params: { credentialId: 'cred-1' } } as never);

it('reads the policy from the configured backend with the verified session', async () => {
    const fetcher = signIn(new Response(JSON.stringify({ id: 'cred-1', approval_operations: [] }), { headers: { 'Content-Type': 'application/json' } }));
    const response = await load();
    expect(fetcher.mock.calls[0][0]).toBe('https://backend.example/api/credential-request/permissions/cred-1');
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer verified-session');
    expect((await response.json()).state.id).toBe('cred-1');
});

it('turns a non-JSON backend failure into a displayable detail instead of throwing', async () => {
    signIn(new Response('<html>Bad Gateway</html>', { status: 502 }));
    const response = await load();
    expect(response.status).toBe(502);
    expect((await response.json()).state.detail).toBe('The server returned 502.');
});
