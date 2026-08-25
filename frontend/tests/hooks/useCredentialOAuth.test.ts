// @vitest-environment jsdom

import { renderHook, act, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type GoogleSuccess = (result: {
    credentialId?: string;
    credentialName?: string;
    credentialType?: string;
    email?: string;
}) => Promise<void> | void;

let googleSuccess: GoogleSuccess | null = null;
const sendEventAsync = vi.fn();
const invalidateCredentialsCache = vi.fn();
const cacheSubscribers = new Set<(change: { added?: Array<Record<string, unknown>>; removed?: string[] }) => void>();

vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: (...args: unknown[]) => sendEventAsync(...args),
}));

vi.mock('~/utils/credentialAutoSelect', () => ({
    getAllCredentialsFromCache: () => [],
    getDisplayOnlyCredentials: () => [],
    invalidateCredentialsCache: () => invalidateCredentialsCache(),
    subscribeCredentialCache: (cb: (change: { added?: Array<Record<string, unknown>>; removed?: string[] }) => void) => {
        cacheSubscribers.add(cb);
        return () => cacheSubscribers.delete(cb);
    },
    upsertCredentialsIntoCache: (creds: Array<Record<string, unknown>>) => {
        cacheSubscribers.forEach((cb) => cb({ added: creds }));
    },
}));

vi.mock('~/hooks/oauth', () => {
    const makeHook = (name: string) => (options: { onSuccess?: GoogleSuccess } = {}) => {
        if (name === 'google') {
            googleSuccess = options.onSuccess ?? null;
        }
        return {
            isConnecting: false,
            connect: vi.fn(),
            selectAccount: vi.fn(),
        };
    };

    return {
        useGoogleOAuth: makeHook('google'),
        useAirtableOAuth: makeHook('airtable'),
        useStripeOAuth: makeHook('stripe'),
        useGithubOAuth: makeHook('github'),
        useGitLabOAuth: makeHook('gitlab'),
        useSalesforceOAuth: makeHook('salesforce'),
        useLinearOAuth: makeHook('linear'),
        useCalComOAuth: makeHook('calcom'),
        useBoxOAuth: makeHook('box'),
        useLinkedInOAuth: makeHook('linkedin'),
        useClickUpOAuth: makeHook('clickup'),
        useRedditOAuth: makeHook('reddit'),
        useNotionOAuth: makeHook('notion'),
        useMicrosoftOAuth: makeHook('microsoft'),
        useDiscordOAuth: makeHook('discord'),
        useDropboxOAuth: makeHook('dropbox'),
        useFacebookOAuth: makeHook('facebook'),
        useFacebookPagesOAuth: makeHook('facebook_pages'),
        useFathomOAuth: makeHook('fathom'),
        useTikTokOAuth: makeHook('tiktok'),
        useTwitterOAuth: makeHook('twitter'),
        useShopifyOAuth: makeHook('shopify'),
        useSlackOAuth: makeHook('slack'),
        useAtlassianOAuth: makeHook('atlassian'),
        useHubSpotOAuth: makeHook('hubspot'),
        useCanvaOAuth: makeHook('canva'),
        useMailchimpOAuth: makeHook('mailchimp'),
        useTypeformOAuth: makeHook('typeform'),
        useWordPressOAuth: makeHook('wordpress'),
        useSupabaseOAuth: makeHook('supabase'),
        useAsanaOAuth: makeHook('asana'),
        useMondayOAuth: makeHook('monday'),
        useAttioOAuth: makeHook('attio'),
        useIntercomOAuth: makeHook('intercom'),
        usePipedriveOAuth: makeHook('pipedrive'),
        useZendeskOAuth: makeHook('zendesk'),
        useBambooHROAuth: makeHook('bamboohr'),
        useKlaviyoOAuth: makeHook('klaviyo'),
        usePagerDutyOAuth: makeHook('pagerduty'),
        useMCPOAuth: makeHook('mcp'),
        useParallelOAuth: makeHook('parallel'),
        useWebflowOAuth: makeHook('webflow'),
        useQuickBooksOAuth: makeHook('quickbooks'),
        useZoomOAuth: makeHook('zoom'),
        useCalendlyOAuth: makeHook('calendly'),
        useSentryOAuth: makeHook('sentry'),
        useThreadsOAuth: makeHook('threads'),
        useCloudflareOAuth: makeHook('cloudflare'),
        usePostHogOAuth: makeHook('posthog'),
        useApolloOAuth: makeHook('apollo'),
        useMetaOAuth: makeHook('meta'),
        useInstagramLoginOAuth: makeHook('instagram_login'),
    };
});

import { useCredentialOAuth } from '~/hooks/useCredentialOAuth';

describe('useCredentialOAuth', () => {
    beforeEach(() => {
        googleSuccess = null;
        sendEventAsync.mockReset();
        invalidateCredentialsCache.mockReset();
        cacheSubscribers.clear();
        sendEventAsync.mockResolvedValue({ credentials: [] });
    });

    it('optimistically exposes a new Google credential when list refresh is still empty', async () => {
        const onCredentialCreated = vi.fn();
        const { result } = renderHook(() => useCredentialOAuth({ onCredentialCreated }));

        await waitFor(() => expect(sendEventAsync).toHaveBeenCalledTimes(1));
        expect(result.current.availableCredentials).toEqual([]);
        expect(googleSuccess).toBeTypeOf('function');

        await act(async () => {
            await googleSuccess?.({
                credentialId: 'cred-firestore-1',
                credentialName: 'firestore-user@example.com',
                credentialType: 'firestore_oauth',
                email: 'firestore-user@example.com',
            });
        });

        await waitFor(() => {
            expect(result.current.availableCredentials).toEqual([
                expect.objectContaining({
                    id: 'cred-firestore-1',
                    name: 'firestore-user@example.com',
                    credential_type: 'firestore_oauth',
                    metadata: { email: 'firestore-user@example.com' },
                }),
            ]);
        });

        expect(invalidateCredentialsCache).toHaveBeenCalledTimes(1);
        expect(sendEventAsync).toHaveBeenCalledTimes(2);
        expect(onCredentialCreated).toHaveBeenCalledWith(
            'cred-firestore-1',
            'google',
            expect.objectContaining({
                id: 'cred-firestore-1',
                name: 'firestore-user@example.com',
                credential_type: 'firestore_oauth',
            }),
        );
    });
});
