import { describe, it, expect } from 'vitest';
import { augmentScopes } from './oauthProviders';

// augmentScopes is the single source of truth for per-provider scope augmentation,
// shared by the in-app connect hooks and the credential-request link. These pin the
// exact behaviour that the link previously got wrong (see credential.provide route).
describe('augmentScopes', () => {
    it('folds Google identity scopes into the request', () => {
        const r = augmentScopes('google', ['https://www.googleapis.com/auth/spreadsheets']);
        expect(r).toContain('email');
        expect(r).toContain('profile');
    });

    it('folds Microsoft User.Read + offline_access into the request', () => {
        const r = augmentScopes('microsoft', ['https://graph.microsoft.com/Mail.Read']);
        expect(r).toContain('offline_access');
        expect(r).toContain('https://graph.microsoft.com/User.Read');
    });

    it('does NOT inject email/profile for Slack — the credential-link bug', () => {
        // Slack rejects email/profile on /oauth/v2/authorize as "Invalid permissions requested".
        const r = augmentScopes('slack', ['channels:read', 'chat:write']);
        expect(r).not.toContain('email');
        expect(r).not.toContain('profile');
        expect(r).toEqual(['channels:read', 'chat:write']);
    });

    it('passes unknown / undefined providers through unchanged', () => {
        expect(augmentScopes('notion', ['read_content'])).toEqual(['read_content']);
        expect(augmentScopes(undefined, ['x'])).toEqual(['x']);
    });

    it('de-duplicates an extra scope that is already requested', () => {
        const r = augmentScopes('google', ['email', 'https://www.googleapis.com/auth/drive']);
        expect(r.filter((s) => s === 'email')).toHaveLength(1);
    });
});
