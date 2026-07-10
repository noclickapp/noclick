// Pins the OAuth provider capabilities that BOTH credential surfaces read from one place:
// which providers need a pre-connect input (Shopify/Zendesk/Atlassian, Confluence-aware) and
// which can't complete on the public provide link (Facebook/Supabase need an in-app selection
// step). Guards the fixes for "the link doesn't ask for the shop" and "the link dead-ends on
// a selection-required provider".

import { describe, it, expect } from 'vitest';
import { oauthNeedsInAppSelection, getOAuthConnectInput } from './oauthProviders';

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
