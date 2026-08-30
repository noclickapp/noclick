// @vitest-environment jsdom
//
// Self-hosted: a credential-optional operation is optional only while the
// instance holds the key that pays for it. In the cloud NoClick's key pays,
// so Exa search, Perplexity and LinkedIn scraping ran credential-less; on a
// one-click deploy the same schemas said "ready" for operations that failed
// on their first run.

import { describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/edition', () => ({ isLocalEdition: () => true }));
vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: vi.fn(async () => null),
}));

const {
    hasUnconnectedCredentials,
    providerCredentialsMissing,
    isUsageBasedBillingAvailable,
    operationPlatformKey,
} = await import('~/components/workflow/NodeCredentials');
const { applyInstanceKeysState } = await import('~/lib/instanceKeys');

const singleOp = (operation: string) => ({ operation, config: { operation } });
const none = {};
const configure = (...envVars: string[]) =>
    applyInstanceKeysState({
        keys: envVars.map((env_var) => ({ env_var, updated_at: null })),
        env_vars: [],
        supported: [],
    });

describe('self-hosted credential-optional operations', () => {
    it('requires a credential for Exa search until the instance holds an Exa key', () => {
        configure();
        expect(
            hasUnconnectedCredentials(
                'automation-exa',
                none,
                singleOp('search')
            )
        ).toBe(true);
        expect(
            providerCredentialsMissing('automation-exa', none, {
                config: { agent_tool_operations: ['search'] },
            })
        ).toBe(true);
        configure('EXA_API_KEY');
        expect(
            hasUnconnectedCredentials(
                'automation-exa',
                none,
                singleOp('search')
            )
        ).toBe(false);
        expect(
            providerCredentialsMissing('automation-exa', none, {
                config: { agent_tool_operations: ['search'] },
            })
        ).toBe(false);
    });

    it('LinkedIn scraping runs on Apify: the node credential never substitutes', () => {
        configure();
        expect(
            operationPlatformKey(
                'automation-linkedin',
                singleOp('scrape_user_profiles')
            )
        ).toEqual({ env: 'APIFY_API_TOKEN', byok: false });
        expect(
            hasUnconnectedCredentials(
                'automation-linkedin',
                none,
                singleOp('scrape_user_profiles')
            )
        ).toBe(true);
        configure('APIFY_API_TOKEN');
        expect(
            hasUnconnectedCredentials(
                'automation-linkedin',
                none,
                singleOp('scrape_user_profiles')
            )
        ).toBe(false);
    });

    it('Exa declares a key the user can replace with their own credential', () => {
        expect(
            operationPlatformKey('automation-exa', singleOp('search'))
        ).toEqual({ env: 'EXA_API_KEY', byok: true });
        expect(
            operationPlatformKey('automation-exa', singleOp('create_webset'))
        ).toBeNull();
    });

    it('a genuinely free operation stays optional without any key', () => {
        configure();
        expect(
            hasUnconnectedCredentials(
                'automation-reddit',
                none,
                singleOp('get_subreddit_posts')
            )
        ).toBe(false);
    });

    it('never advertises the cloud\u2019s usage-based billing', () => {
        configure('EXA_API_KEY');
        expect(
            isUsageBasedBillingAvailable('automation-exa', singleOp('search'))
        ).toBe(false);
    });
});
