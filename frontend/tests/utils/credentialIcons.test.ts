// Verifies credential-icon resolution for the surfaces that previously fell
// through to the generic key or the wrong color: agent provider credentials
// (agent_<provider>), the Discord OAuth type, and legacy raw-title node
// credentials (e.g. `instagrampageaccesstokencredential`). Added alongside the
// fix that centralized harness brand marks into ~/lib/harnessBrand and indexed
// node credentials under their raw schema title.

import { describe, it, expect, beforeAll } from 'vitest';
import { KeyRound } from 'lucide-react';
import { getCredentialIcon, getOAuthProviderIcon } from '~/utils/credentialIcons';
import { OAUTH_PROVIDER_SETUP } from '~/lib/oauthProviderSetup';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

// getCredentialIcon resolves node-backed types from the icon singleton (normally
// populated by the dashboard loader). Seed the two nodes the node-backed cases
// below need before any node-backed lookup builds the internal cache.
beforeAll(() => {
    const dims = { width: 90, height: 90, iconSize: 48 };
    setNodeIconData({
        'automation-instagram': {
            type: 'automation-instagram',
            label: 'Instagram',
            description: '',
            iconColor: 'text-pink-500',
            iconHtml: '<svg data-icon="instagram" />',
            dimensions: dims,
        },
        // Every node type, so node-backed OAuth providers resolve the way they do
        // once the dashboard loader has run.
        ...Object.fromEntries(Object.keys(NODE_SCHEMAS).map((type) => [type, { type, label: type, description: '', iconColor: '', iconHtml: `<svg data-icon="${type}" />`, dimensions: dims }])),
        'automation-telegram': {
            type: 'automation-telegram',
            label: 'Telegram',
            description: '',
            iconColor: '',
            iconHtml: '<svg data-icon="telegram" />',
            dimensions: dims,
        },
    });
});

describe('getCredentialIcon — agent provider credentials', () => {
    // The screenshot cases plus the openai/anthropic siblings — all must resolve
    // to a real brand mark rather than the generic key.
    it.each([
        'agent_openrouter',
        'agent_opencode',
        'agent_hermes_agent',
        'agent_openclaw',
        'agent_openai',
        'agent_anthropic',
        'agent_codex',
    ])('%s resolves to a service icon (not the generic key)', (credType) => {
        const { Icon, hasServiceIcon } = getCredentialIcon(credType);
        expect(hasServiceIcon).toBe(true);
        expect(Icon).not.toBe(KeyRound);
    });

    it('preserves the existing agent_api_key / OAuth-alias entries', () => {
        expect(getCredentialIcon('agent_api_key').hasServiceIcon).toBe(true);
        expect(getCredentialIcon('agent_codex_oauth').hasServiceIcon).toBe(true);
        expect(getCredentialIcon('agent_claude_code_oauth').hasServiceIcon).toBe(true);
    });
});

describe('getCredentialIcon — Discord OAuth', () => {
    it('resolves discord_oauth to the Discord brand mark, untinted', () => {
        // Credential surfaces render the Discord mark neutral (no brand tint);
        // the canvas node keeps full-color brand. See oauthProviders.discord.
        const { hasServiceIcon, iconColor } = getCredentialIcon('discord_oauth');
        expect(hasServiceIcon).toBe(true);
        expect(iconColor).toBe('');
    });

    it('oauthProviders maps discord_oauth to the discord provider', () => {
        const cfg = getProviderConfigByCredentialType('discord_oauth');
        expect(cfg?.oauthProvider).toBe('discord');
    });
});

describe('getCredentialIcon — node credentials by canonical and raw title', () => {
    it('resolves the canonical instagram_page_access_token type', () => {
        expect(getCredentialIcon('instagram_page_access_token').hasServiceIcon).toBe(true);
    });

    it('resolves the legacy raw schema-title credential type', () => {
        // Legacy SDK-created credentials stored the lowercased schema title verbatim.
        const { hasServiceIcon } = getCredentialIcon('instagrampageaccesstokencredential');
        expect(hasServiceIcon).toBe(true);
    });

    it('still falls back to the generic key for unknown types', () => {
        const { Icon, hasServiceIcon } = getCredentialIcon('totally_unknown_service');
        expect(hasServiceIcon).toBe(false);
        expect(Icon).toBe(KeyRound);
    });
});

describe('getOAuthProviderIcon — the OAuth-app picker', () => {
    // A family provider (Google, Microsoft, Atlassian, Intuit) owns no
    // `<provider>_oauth` credential type, so a type-based lookup showed the
    // generic key next to "Google" in the picker.
    it.each(Object.keys(OAUTH_PROVIDER_SETUP))('%s resolves to a service icon', (provider) => {
        const { Icon, hasServiceIcon } = getOAuthProviderIcon(provider);
        expect(hasServiceIcon).toBe(true);
        expect(Icon).not.toBe(KeyRound);
    });

    it('family providers get their colour marks, not a tinted glyph', () => {
        expect(getOAuthProviderIcon('google').iconColor).toBe('');
        expect(getOAuthProviderIcon('microsoft').iconColor).toBe('');
        expect(getOAuthProviderIcon('atlassian').iconColor).toBe('#0052CC');
    });
});
