// Pins the OAuth provider capabilities that BOTH credential surfaces read from one place:
// which providers need a pre-connect input (Shopify/Zendesk/Atlassian, Confluence-aware),
// which can't complete on the public provide link (Facebook/Supabase need an in-app
// selection step), and per-provider scope augmentation (augmentScopes — the single source
// shared by the connect hooks, the createOAuthHook factory, and the credential-request link).

import { describe, it, expect } from 'vitest';
import { oauthNeedsInAppSelection, getOAuthConnectInput, augmentScopes } from './oauthProviders';

describe('oauthProviders connect capabilities', () => {
    it('flags providers whose OAuth needs an in-app selection step', () => {
        expect(oauthNeedsInAppSelection('facebook')).toBe(true);
        expect(oauthNeedsInAppSelection('supabase')).toBe(true);
        expect(oauthNeedsInAppSelection('linear')).toBe(false);
        expect(oauthNeedsInAppSelection(undefined)).toBe(false);
    });

    it('resolves provider-intrinsic pre-connect inputs, Confluence-aware', () => {
        expect(getOAuthConnectInput('shopify', 'shopify_oauth')?.kind).toBe('shop');
        expect(getOAuthConnectInput('zendesk', 'zendesk_oauth')?.kind).toBe('subdomain');
        expect(getOAuthConnectInput('atlassian', 'jira_oauth')?.label).toBe('Jira site');
        expect(getOAuthConnectInput('atlassian', 'confluence_oauth')?.label).toBe('Confluence site');
        expect(getOAuthConnectInput('linear', 'linear_oauth')).toBeUndefined();
    });
});

// augmentScopes is the single source of truth for per-provider scope augmentation,
// shared by the in-app connect hooks, the createOAuthHook factory, and the credential
// link. These pin the exact behaviour the link previously got wrong.
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
