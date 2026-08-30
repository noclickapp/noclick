// The one invariant that keeps self-hosted sessions alive: the server (built
// on the internal Supabase URL) and the browser (built on the public URL)
// must write and read the SAME auth cookie. Off localhost their library
// defaults diverge, which left every Railway deploy with a session the
// browser could not see and a missing_auth socket loop (2026-08-31).
import { describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/edition', () => ({ isLocalEdition: () => true }));

const { authCookieName, devAuthCookieName, SELF_HOST_AUTH_COOKIE_NAME } = await import('~/lib/supabase-client');

describe('authCookieName (self-hosted)', () => {
    it('pins one name for any public host, so both sides always agree', () => {
        expect(authCookieName('noclick-production-8103.up.railway.app', '')).toBe(SELF_HOST_AUTH_COOKIE_NAME);
        expect(authCookieName('noclick.example.com', '443')).toBe(SELF_HOST_AUTH_COOKIE_NAME);
        // (The server names the cookie from the REQUEST host — the forwarded
        // public domain — never from the internal 127.0.0.1 Supabase URL,
        // which is exactly the derivation this constant replaces.)
    });

    it('keeps the per-worktree name on a localhost dev server', () => {
        expect(authCookieName('localhost', '5173')).toBe('sb-noclick-wt5173-auth-token');
        expect(devAuthCookieName('localhost', '5173')).toBe('sb-noclick-wt5173-auth-token');
    });
});
