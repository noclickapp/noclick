import { describe, expect, it } from 'vitest';
import { worktreeRedirect } from '~/lib/devHost';
import { isLoopbackHostname } from '~/lib/loopback';

const navigate = (host: string, cookie = '', url = '/dashboard?tab=chat') => ({
    method: 'GET',
    url,
    headers: { host, cookie, 'sec-fetch-mode': 'navigate' },
});

describe('worktreeRedirect', () => {
    it("moves a page load on the shared localhost jar to the worktree's own host", () => {
        expect(worktreeRedirect(navigate('localhost:5180'))).toEqual({
            location: 'http://wt5180.localhost:5180/dashboard?tab=chat',
            expire: [],
        });
        expect(worktreeRedirect(navigate('127.0.0.1:5173', '', '/'))?.location).toBe('http://wt5173.localhost:5173/');
    });

    it("expires this worktree's old session and the pre-namespacing one, never another worktree's", () => {
        const cookie = [
            'sb-noclick-wt5180-auth-token.0=a',
            'sb-noclick-wt5180-auth-token.1=b',
            'sb-noclick-wt5180-auth-token-code-verifier=c',
            'sb-noclick-wt5173-auth-token.0=d',
            'sb-127-auth-token.0=e',
            'csrf_token=f',
        ].join('; ');
        expect(worktreeRedirect(navigate('localhost:5180', cookie))?.expire).toEqual([
            'sb-noclick-wt5180-auth-token.0=; Max-Age=0; Path=/',
            'sb-noclick-wt5180-auth-token.1=; Max-Age=0; Path=/',
            'sb-noclick-wt5180-auth-token-code-verifier=; Max-Age=0; Path=/',
            'sb-127-auth-token.0=; Max-Age=0; Path=/',
        ]);
    });

    it("clears every worktree's session off 127.0.0.1, which the local Supabase API shares", () => {
        const cookie = 'sb-noclick-wt5173-auth-token.0=a; sb-noclick-wt5174-auth-token.1=b; sb-127-auth-token.0=c; ph_phc_x_posthog=d';
        expect(worktreeRedirect(navigate('127.0.0.1:5180', cookie))?.expire).toEqual([
            'sb-noclick-wt5173-auth-token.0=; Max-Age=0; Path=/',
            'sb-noclick-wt5174-auth-token.1=; Max-Age=0; Path=/',
            'sb-127-auth-token.0=; Max-Age=0; Path=/',
        ]);
    });

    it('leaves fetches, posts, HMR and already-isolated hosts alone', () => {
        expect(worktreeRedirect(navigate('wt5180.localhost:5180'))).toBeNull();
        expect(worktreeRedirect({ ...navigate('localhost:5180'), method: 'POST' })).toBeNull();
        expect(worktreeRedirect({ method: 'GET', url: '/__nc', headers: { host: 'localhost:5180' } })).toBeNull();
        expect(worktreeRedirect({ method: 'GET', url: '/', headers: { host: 'localhost:5180', 'sec-fetch-mode': 'cors' } })).toBeNull();
        expect(worktreeRedirect(navigate('noclick.com'))).toBeNull();
    });
});

describe('isLoopbackHostname', () => {
    it('accepts localhost, 127.0.0.1 and *.localhost, nothing else', () => {
        expect(['localhost', '127.0.0.1', 'wt5180.localhost'].map(isLoopbackHostname)).toEqual([true, true, true]);
        expect(['noclick.com', 'localhost.evil.com', '', undefined].map(isLoopbackHostname)).toEqual([false, false, false, false]);
    });
});
