// The one invariant that keeps sessions alive: the server and the browser must
// write and read the SAME auth cookie, and that name must not move under the
// people already signed in. Self-hosted, the library defaults diverge between
// the two sides (the server is built on the internal Supabase URL), which left
// every Railway deploy with a session the browser could not see and a
// missing_auth socket loop (2026-08-31). Hosted, the default follows the
// Supabase URL, so moving that URL would rename the cookie and sign everyone out.
import { afterEach, describe, expect, it, vi } from 'vitest';

const edition = vi.hoisted(() => ({ local: true }));
vi.mock('~/lib/edition', () => ({ isLocalEdition: () => edition.local }));

const { authCookieName, devAuthCookieName, HOSTED_AUTH_COOKIE_NAME, SELF_HOST_AUTH_COOKIE_NAME } = await import(
    '~/lib/supabase-client'
);

afterEach(() => {
    edition.local = true;
});

describe('authCookieName (self-hosted)', () => {
    it('pins one name for any public host, so both sides always agree', () => {
        expect(authCookieName('noclick-production-8103.up.railway.app', '')).toBe(SELF_HOST_AUTH_COOKIE_NAME);
        expect(authCookieName('noclick.example.com', '443')).toBe(SELF_HOST_AUTH_COOKIE_NAME);
        expect(SELF_HOST_AUTH_COOKIE_NAME).toBe('sb-noclick-auth-token');
        // (The server names the cookie from the REQUEST host — the forwarded
        // public domain — never from the internal 127.0.0.1 Supabase URL,
        // which is exactly the derivation this constant replaces.)
    });

    it('keeps the per-worktree name on a localhost dev server', () => {
        expect(authCookieName('localhost', '5173')).toBe('sb-noclick-wt5173-auth-token');
        expect(devAuthCookieName('localhost', '5173')).toBe('sb-noclick-wt5173-auth-token');
    });
});

describe('authCookieName (hosted)', () => {
    it('is the name hosted sessions already carry, on every hosted host', () => {
        edition.local = false;
        expect(HOSTED_AUTH_COOKIE_NAME).toBe('sb-api-auth-token');
        for (const host of ['noclick.com', 'www.noclick.com', 'staging.example.test', 'noclick-git-x.vercel.app']) {
            expect(authCookieName(host, '')).toBe('sb-api-auth-token');
        }
    });

    it('still gives a hosted dev server its per-worktree name', () => {
        edition.local = false;
        expect(authCookieName('wt5180.localhost', '5180')).toBe('sb-noclick-wt5180-auth-token');
        expect(authCookieName('localhost', '5173')).toBe('sb-noclick-wt5173-auth-token');
    });
});
