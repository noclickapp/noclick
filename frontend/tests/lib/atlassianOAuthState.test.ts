import { afterEach, describe, expect, it } from 'vitest';
import {
    decodeAtlassianOAuthState,
    encodeAtlassianOAuthState,
    type AtlassianOAuthState,
} from '~/utils/atlassianOAuthState.server';

const ORIGINAL_ENV = { ...process.env };

afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
});

function state(): AtlassianOAuthState {
    return {
        credentialName: 'Jira',
        scopes: ['read:jira-work'],
        appOrigin: 'https://app.example.com',
        redirectUri: 'https://app.example.com/api/auth/atlassian/callback',
        nonce: 'nonce',
        timestamp: Date.now(),
    };
}

describe('Atlassian OAuth state signing', () => {
    it('never treats the public client id as an HMAC secret', () => {
        delete process.env.ATLASSIAN_STATE_SECRET;
        delete process.env.SESSION_SECRET;
        delete process.env.ATLASSIAN_CLIENT_SECRET;
        process.env.ATLASSIAN_CLIENT_ID = 'public-client-id';

        expect(() => encodeAtlassianOAuthState(state())).toThrow(
            'ATLASSIAN_STATE_SECRET, SESSION_SECRET, or ATLASSIAN_CLIENT_SECRET',
        );
    });

    it('round-trips with the instance session secret', () => {
        process.env.SESSION_SECRET = 'a-real-secret-used-only-by-this-test';
        const encoded = encodeAtlassianOAuthState(state());
        expect(decodeAtlassianOAuthState(encoded).credentialName).toBe('Jira');
    });
});
