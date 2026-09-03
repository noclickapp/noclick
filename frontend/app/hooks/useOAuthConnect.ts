/**
 * useOAuthConnect - The provider OAuth connect engine, split out of useCredentialOAuth.
 * Instantiates every provider OAuth hook, dispatches connect() by provider, and manages
 * connecting / pending-selection state. It does NOT list or cache credentials — that's the
 * in-app credential manager's job (useCredentialOAuth wraps this and adds it). Because the
 * exchange runs through OAuthExchangeContext, this same engine powers both the authenticated
 * in-app UI (socket transport) and the public credential-provide page (HTTP transport).
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { toast } from 'sonner';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { providerSupportsOrgConsent } from '~/utils/oauthProviders';
import {
    useGoogleOAuth, useAirtableOAuth, useStripeOAuth, useGithubOAuth, useGitLabOAuth,
    useSalesforceOAuth, useLinearOAuth, useCalComOAuth, useBoxOAuth, useAsanaOAuth,
    useMondayOAuth, useAttioOAuth, useIntercomOAuth, usePipedriveOAuth, usePagerDutyOAuth,
    useWebflowOAuth, useLinkedInOAuth, useClickUpOAuth, useZendeskOAuth, useBambooHROAuth, useKlaviyoOAuth, useRedditOAuth,
    useNotionOAuth, useMicrosoftOAuth, useDiscordOAuth, useDropboxOAuth, useFacebookOAuth, useFacebookPagesOAuth,
    useFathomOAuth, useTikTokOAuth, useTwitterOAuth, useShopifyOAuth, useSlackOAuth,
    useAtlassianOAuth, useHubSpotOAuth, useCanvaOAuth, useMailchimpOAuth, useTypeformOAuth,
    useWordPressOAuth, useSupabaseOAuth, useParallelOAuth, useQuickBooksOAuth, useZoomOAuth, useCalendlyOAuth, useSentryOAuth, useThreadsOAuth, useCloudflareOAuth, usePostHogOAuth, useApolloOAuth, useMetaOAuth, useInstagramLoginOAuth,
} from '~/hooks/oauth';
import type { AtlassianSiteSuggestion } from '~/hooks/oauth/useAtlassianOAuth';

export interface OAuthSelectionOption {
    id: string;
    label?: string;
    description?: string;
    data?: object;
}

export interface OAuthPendingSelection {
    provider: string;
    options: OAuthSelectionOption[];
}

export interface OAuthCreatedCredential {
    id: string;
    name: string;
    credential_type: string;
    metadata?: Record<string, unknown>;
}

export interface UseOAuthConnectOptions {
    /** Fired when a credential is successfully created via OAuth. */
    onCredentialCreated?: (credentialId: string, provider: string, credential?: OAuthCreatedCredential) => void;
    /** Fired on an OAuth error (excludes plan-limit errors, which route to planLimitError). */
    onError?: (error: string) => void;
    /** Fired when the popup is closed without completing (cancellation). */
    onCancel?: () => void;
    /** Internal: run right after a successful OAuth mint, before onCredentialCreated —
     *  the in-app manager uses it to invalidate + reload its credential list/cache. */
    onAfterOAuthCredential?: (credential?: OAuthCreatedCredential) => void | Promise<void>;
}

type OAuthHook = {
    isConnecting: boolean;
    connect: (...args: unknown[]) => unknown;
};

export function useOAuthConnect(options: UseOAuthConnectOptions = {}) {
    const { onError } = options;

    const [error, setError] = useState<string | null>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const [connectingProvider, setConnectingProvider] = useState<string | null>(null);
    const [pendingSelection, setPendingSelection] = useState<OAuthPendingSelection | null>(null);
    const atlassianSuggestionRef = useRef<AtlassianSiteSuggestion | null>(null);
    const pendingSelectionResolverRef = useRef<((optionId: string) => Promise<void>) | null>(null);

    const optionsRef = useRef(options);
    optionsRef.current = options;

    // Success handler factory — builds the created-credential descriptor, lets the caller
    // do any post-success bookkeeping (list reload), then notifies onCredentialCreated.
    const createSuccessHandler = useCallback((provider: string) => {
        return async (result: { credentialId?: string; credentialName?: string; credentialType?: string; email?: string }) => {
            setConnectingProvider(null);
            setPendingSelection(null);
            atlassianSuggestionRef.current = null;
            pendingSelectionResolverRef.current = null;
            const createdCredential = (
                result.credentialId && result.credentialType && result.credentialName
            ) ? {
                id: result.credentialId,
                name: result.credentialName,
                credential_type: result.credentialType,
                metadata: result.email ? { email: result.email } : undefined,
            } satisfies OAuthCreatedCredential : undefined;
            await optionsRef.current.onAfterOAuthCredential?.(createdCredential);
            if (result.credentialId) {
                optionsRef.current.onCredentialCreated?.(result.credentialId, provider, createdCredential);
            }
        };
    }, []);

    // Error handler factory — routes plan-limit errors aside; empty message = cancellation.
    const createErrorHandler = useCallback((provider: string) => {
        return (errorMsg: string) => {
            setConnectingProvider(null);
            setPendingSelection(null);
            atlassianSuggestionRef.current = null;
            pendingSelectionResolverRef.current = null;
            if (!errorMsg) { optionsRef.current.onCancel?.(); return; }
            console.error(`[useOAuthConnect] ${provider} OAuth error:`, errorMsg);
            if (isPlanLimitError(errorMsg)) setPlanLimitError(errorMsg);
            else setError(errorMsg);
            // Toast as well: the inline error panel only renders while the
            // credential form is mounted — a popup that dies after the form
            // unmounts (or behind a dialog) must still tell the user.
            toast.error(`${provider} connection failed: ${errorMsg}`);
            onError?.(errorMsg);
        };
    }, [onError]);

    const googleOAuth = useGoogleOAuth({ onSuccess: createSuccessHandler('google'), onError: createErrorHandler('google') });
    const airtableOAuth = useAirtableOAuth({ onSuccess: createSuccessHandler('airtable'), onError: createErrorHandler('airtable') });
    const stripeOAuth = useStripeOAuth({ onSuccess: createSuccessHandler('stripe'), onError: createErrorHandler('stripe') });
    const githubOAuth = useGithubOAuth({ onSuccess: createSuccessHandler('github'), onError: createErrorHandler('github') });
    const gitlabOAuth = useGitLabOAuth({ onSuccess: createSuccessHandler('gitlab'), onError: createErrorHandler('gitlab') });
    const salesforceOAuth = useSalesforceOAuth({ onSuccess: createSuccessHandler('salesforce'), onError: createErrorHandler('salesforce') });
    const linearOAuth = useLinearOAuth({ onSuccess: createSuccessHandler('linear'), onError: createErrorHandler('linear') });
    const calcomOAuth = useCalComOAuth({ onSuccess: createSuccessHandler('calcom'), onError: createErrorHandler('calcom') });
    const boxOAuth = useBoxOAuth({ onSuccess: createSuccessHandler('box'), onError: createErrorHandler('box') });
    const asanaOAuth = useAsanaOAuth({ onSuccess: createSuccessHandler('asana'), onError: createErrorHandler('asana') });
    const mondayOAuth = useMondayOAuth({ onSuccess: createSuccessHandler('monday'), onError: createErrorHandler('monday') });
    const attioOAuth = useAttioOAuth({ onSuccess: createSuccessHandler('attio'), onError: createErrorHandler('attio') });
    const intercomOAuth = useIntercomOAuth({ onSuccess: createSuccessHandler('intercom'), onError: createErrorHandler('intercom') });
    const pipedriveOAuth = usePipedriveOAuth({ onSuccess: createSuccessHandler('pipedrive'), onError: createErrorHandler('pipedrive') });
    const pagerdutyOAuth = usePagerDutyOAuth({ onSuccess: createSuccessHandler('pagerduty'), onError: createErrorHandler('pagerduty') });
    const webflowOAuth = useWebflowOAuth({ onSuccess: createSuccessHandler('webflow'), onError: createErrorHandler('webflow') });
    const linkedinOAuth = useLinkedInOAuth({ onSuccess: createSuccessHandler('linkedin'), onError: createErrorHandler('linkedin') });
    const clickupOAuth = useClickUpOAuth({ onSuccess: createSuccessHandler('clickup'), onError: createErrorHandler('clickup') });
    const zendeskOAuth = useZendeskOAuth({ onSuccess: createSuccessHandler('zendesk'), onError: createErrorHandler('zendesk') });
    const bamboohrOAuth = useBambooHROAuth({ onSuccess: createSuccessHandler('bamboohr'), onError: createErrorHandler('bamboohr') });
    const klaviyoOAuth = useKlaviyoOAuth({ onSuccess: createSuccessHandler('klaviyo'), onError: createErrorHandler('klaviyo') });
    const redditOAuth = useRedditOAuth({ onSuccess: createSuccessHandler('reddit'), onError: createErrorHandler('reddit') });
    const notionOAuth = useNotionOAuth({ onSuccess: createSuccessHandler('notion'), onError: createErrorHandler('notion') });
    const microsoftOAuth = useMicrosoftOAuth({ onSuccess: createSuccessHandler('microsoft'), onError: createErrorHandler('microsoft') });
    const discordOAuth = useDiscordOAuth({ onSuccess: createSuccessHandler('discord'), onError: createErrorHandler('discord') });
    const dropboxOAuth = useDropboxOAuth({ onSuccess: createSuccessHandler('dropbox'), onError: createErrorHandler('dropbox') });
    const facebookOAuth = useFacebookOAuth({
        onSuccess: createSuccessHandler('facebook'),
        onError: createErrorHandler('facebook'),
        onNeedsSelection: (accounts) => {
            const opts: OAuthSelectionOption[] = (accounts || []).map((account) => {
                const pageLabel = account.facebook_page_name || account.facebook_page_id;
                return {
                    id: account.instagram_user_id,
                    label: account.instagram_username ? `@${account.instagram_username}` : account.instagram_user_id,
                    description: pageLabel ? `Page: ${pageLabel}` : undefined,
                    data: account,
                };
            });
            setPendingSelection({ provider: 'facebook', options: opts });
            pendingSelectionResolverRef.current = async (optionId: string) => { await facebookOAuth.selectAccount(optionId); };
            setConnectingProvider(null);
            setError(null);
        },
    });
    const facebookPagesOAuth = useFacebookPagesOAuth({ onSuccess: createSuccessHandler('facebook_pages'), onError: createErrorHandler('facebook_pages') });
    const fathomOAuth = useFathomOAuth({ onSuccess: createSuccessHandler('fathom'), onError: createErrorHandler('fathom') });
    const threadsOAuth = useThreadsOAuth({ onSuccess: createSuccessHandler('threads'), onError: createErrorHandler('threads') });
    const metaOAuth = useMetaOAuth({ onSuccess: createSuccessHandler('meta'), onError: createErrorHandler('meta') });
    const instagramLoginOAuth = useInstagramLoginOAuth({ onSuccess: createSuccessHandler('instagram_login'), onError: createErrorHandler('instagram_login') });
    const tiktokOAuth = useTikTokOAuth({ onSuccess: createSuccessHandler('tiktok'), onError: createErrorHandler('tiktok') });
    const twitterOAuth = useTwitterOAuth({ onSuccess: createSuccessHandler('twitter'), onError: createErrorHandler('twitter') });
    const shopifyOAuth = useShopifyOAuth({ onSuccess: createSuccessHandler('shopify'), onError: createErrorHandler('shopify') });
    const slackOAuth = useSlackOAuth({ onSuccess: createSuccessHandler('slack'), onError: createErrorHandler('slack') });
    const atlassianOAuth = useAtlassianOAuth({
        onSuccess: createSuccessHandler('atlassian'),
        onError: createErrorHandler('atlassian'),
        onSiteSuggestion: (suggestion) => {
            atlassianSuggestionRef.current = suggestion;
            setPendingSelection({
                provider: 'atlassian',
                options: suggestion.availableSites.map(site => ({
                    id: site.url,
                    label: site.name || site.url.replace(/^https?:\/\//, ''),
                    description: site.url,
                    data: site,
                })),
            });
            pendingSelectionResolverRef.current = async (siteUrl: string) => { await suggestion.useSite(siteUrl); };
            setConnectingProvider(null);
            setError(suggestion.message);
        },
    });
    const hubspotOAuth = useHubSpotOAuth({ onSuccess: createSuccessHandler('hubspot'), onError: createErrorHandler('hubspot') });
    const canvaOAuth = useCanvaOAuth({ onSuccess: createSuccessHandler('canva'), onError: createErrorHandler('canva') });
    const mailchimpOAuth = useMailchimpOAuth({ onSuccess: createSuccessHandler('mailchimp'), onError: createErrorHandler('mailchimp') });
    const typeformOAuth = useTypeformOAuth({ onSuccess: createSuccessHandler('typeform'), onError: createErrorHandler('typeform') });
    const wordpressOAuth = useWordPressOAuth({ onSuccess: createSuccessHandler('wordpress'), onError: createErrorHandler('wordpress') });
    const supabaseOAuth = useSupabaseOAuth({
        onSuccess: createSuccessHandler('supabase'),
        onError: createErrorHandler('supabase'),
        onNeedsSelection: (projects, pendingId) => {
            const opts = projects.map((p) => ({ id: p.ref, label: p.name, data: { ref: p.ref, name: p.name, pending_id: pendingId } }));
            setPendingSelection({ provider: 'supabase', options: opts });
            pendingSelectionResolverRef.current = async (projectRef: string) => { await supabaseOAuth.selectProject(projectRef, pendingId); };
            setConnectingProvider(null);
            setError(null);
        },
    });
    const parallelOAuth = useParallelOAuth({ onSuccess: createSuccessHandler('parallel'), onError: createErrorHandler('parallel') });
    const quickbooksOAuth = useQuickBooksOAuth({ onSuccess: createSuccessHandler('quickbooks'), onError: createErrorHandler('quickbooks') });
    const zoomOAuth = useZoomOAuth({ onSuccess: createSuccessHandler('zoom'), onError: createErrorHandler('zoom') });
    const calendlyOAuth = useCalendlyOAuth({ onSuccess: createSuccessHandler('calendly'), onError: createErrorHandler('calendly') });
    const sentryOAuth = useSentryOAuth({ onSuccess: createSuccessHandler('sentry'), onError: createErrorHandler('sentry') });
    const cloudflareOAuth = useCloudflareOAuth({ onSuccess: createSuccessHandler('cloudflare'), onError: createErrorHandler('cloudflare') });
    const posthogOAuth = usePostHogOAuth({ onSuccess: createSuccessHandler('posthog'), onError: createErrorHandler('posthog') });
    const apolloOAuth = useApolloOAuth({ onSuccess: createSuccessHandler('apollo'), onError: createErrorHandler('apollo') });

    const oauthHookMap = useMemo<Record<string, OAuthHook>>(() => ({
        'google': googleOAuth as unknown as OAuthHook,
        'airtable': airtableOAuth as unknown as OAuthHook,
        'stripe': stripeOAuth as unknown as OAuthHook,
        'github': githubOAuth as unknown as OAuthHook,
        'gitlab': gitlabOAuth as unknown as OAuthHook,
        'salesforce': salesforceOAuth as unknown as OAuthHook,
        'linear': linearOAuth as unknown as OAuthHook,
        'calcom': calcomOAuth as unknown as OAuthHook,
        'box': boxOAuth as unknown as OAuthHook,
        'asana': asanaOAuth as unknown as OAuthHook,
        'monday': mondayOAuth as unknown as OAuthHook,
        'attio': attioOAuth as unknown as OAuthHook,
        'intercom': intercomOAuth as unknown as OAuthHook,
        'pipedrive': pipedriveOAuth as unknown as OAuthHook,
        'pagerduty': pagerdutyOAuth as unknown as OAuthHook,
        'webflow': webflowOAuth as unknown as OAuthHook,
        'linkedin': linkedinOAuth as unknown as OAuthHook,
        'clickup': clickupOAuth as unknown as OAuthHook,
        'zendesk': zendeskOAuth as unknown as OAuthHook,
        'bamboohr': bamboohrOAuth as unknown as OAuthHook,
        'klaviyo': klaviyoOAuth as unknown as OAuthHook,
        'reddit': redditOAuth as unknown as OAuthHook,
        'notion': notionOAuth as unknown as OAuthHook,
        'microsoft': microsoftOAuth as unknown as OAuthHook,
        'discord': discordOAuth as unknown as OAuthHook,
        'dropbox': dropboxOAuth as unknown as OAuthHook,
        'facebook': facebookOAuth as unknown as OAuthHook,
        'facebook_pages': facebookPagesOAuth as unknown as OAuthHook,
        'fathom': fathomOAuth as unknown as OAuthHook,
        'threads': threadsOAuth as unknown as OAuthHook,
        'meta': metaOAuth as unknown as OAuthHook,
        'instagram_login': instagramLoginOAuth as unknown as OAuthHook,
        'tiktok': tiktokOAuth as unknown as OAuthHook,
        'twitter': twitterOAuth as unknown as OAuthHook,
        'shopify': shopifyOAuth as unknown as OAuthHook,
        'slack': slackOAuth as unknown as OAuthHook,
        'atlassian': atlassianOAuth as unknown as OAuthHook,
        'hubspot': hubspotOAuth as unknown as OAuthHook,
        'canva': canvaOAuth as unknown as OAuthHook,
        'mailchimp': mailchimpOAuth as unknown as OAuthHook,
        'typeform': typeformOAuth as unknown as OAuthHook,
        'wordpress': wordpressOAuth as unknown as OAuthHook,
        'supabase': supabaseOAuth as unknown as OAuthHook,
        'parallel': parallelOAuth as unknown as OAuthHook,
        'quickbooks': quickbooksOAuth as unknown as OAuthHook,
        'zoom': zoomOAuth as unknown as OAuthHook,
        'calendly': calendlyOAuth as unknown as OAuthHook,
        'sentry': sentryOAuth as unknown as OAuthHook,
        'cloudflare': cloudflareOAuth as unknown as OAuthHook,
        'posthog': posthogOAuth as unknown as OAuthHook,
        'apollo': apolloOAuth as unknown as OAuthHook,
    }), [
        googleOAuth, airtableOAuth, stripeOAuth, githubOAuth, gitlabOAuth, salesforceOAuth,
        linearOAuth, calcomOAuth, boxOAuth, asanaOAuth, mondayOAuth, attioOAuth, intercomOAuth,
        pipedriveOAuth, pagerdutyOAuth, webflowOAuth, linkedinOAuth, clickupOAuth, zendeskOAuth, bamboohrOAuth, klaviyoOAuth,
        redditOAuth, notionOAuth, microsoftOAuth, discordOAuth, dropboxOAuth, facebookOAuth, facebookPagesOAuth, threadsOAuth,
        fathomOAuth, tiktokOAuth, twitterOAuth, shopifyOAuth, slackOAuth, atlassianOAuth,
        hubspotOAuth, canvaOAuth, mailchimpOAuth, typeformOAuth, wordpressOAuth, supabaseOAuth,
        parallelOAuth, quickbooksOAuth, zoomOAuth, calendlyOAuth, sentryOAuth, cloudflareOAuth, posthogOAuth, apolloOAuth,
        metaOAuth, instagramLoginOAuth,
    ]);

    const connect = useCallback((
        provider: string,
        name: string,
        scopes?: string[],
        shopName?: string,
        atlassianSite?: string,
        userScopes?: string[],
        customClientCredentials?: { client_id: string; client_secret: string },
    ) => {
        const hook = oauthHookMap[provider];
        if (!hook) {
            const errorMsg = `Unknown OAuth provider: ${provider}`;
            setError(errorMsg);
            onError?.(errorMsg);
            return;
        }
        setError(null);
        setPlanLimitError(null);
        setConnectingProvider(provider);
        setPendingSelection(null);
        atlassianSuggestionRef.current = null;
        pendingSelectionResolverRef.current = null;

        if (provider === 'shopify' && shopName) {
            hook.connect(name, shopName, scopes || [], customClientCredentials?.client_id, customClientCredentials?.client_secret);
        } else if (provider === 'zendesk' && shopName) {
            hook.connect(name, shopName, scopes || []);
        } else if (provider === 'zendesk') {
            const errorMsg = 'Zendesk subdomain is required to connect Zendesk OAuth';
            setError(errorMsg); setConnectingProvider(null); onError?.(errorMsg);
        } else if (provider === 'bamboohr' && shopName) {
            hook.connect(name, shopName, scopes || []);
        } else if (provider === 'bamboohr') {
            const errorMsg = 'BambooHR company subdomain is required to connect BambooHR OAuth';
            setError(errorMsg); setConnectingProvider(null); onError?.(errorMsg);
        } else if (provider === 'atlassian' && atlassianSite) {
            hook.connect(name, scopes || [], atlassianSite);
        } else if (provider === 'atlassian') {
            const errorMsg = 'Jira site is required to connect Atlassian OAuth';
            setError(errorMsg); setConnectingProvider(null); onError?.(errorMsg);
        } else if (provider === 'supabase') {
            hook.connect(name);
        } else if (provider === 'slack') {
            hook.connect(name, scopes || [], undefined, undefined, userScopes || []);
        } else if (provider === 'google' && customClientCredentials) {
            hook.connect(name, scopes || [], customClientCredentials);
        } else if (provider === 'quickbooks' && customClientCredentials) {
            hook.connect(name, scopes || [], customClientCredentials.client_id, customClientCredentials.client_secret);
        } else {
            hook.connect(name, scopes || []);
        }
    }, [oauthHookMap, onError]);

    // Tenant-wide admin consent (Microsoft's "Need admin approval" wall): the same popup
    // engine, provider-gated. Only factory hooks take the options arg, and only they carry
    // `supportsOrgConsent`, so the gate is what keeps a bespoke hook from silently ignoring it.
    const connectOrgConsent = useCallback((provider: string, name: string, scopes?: string[]) => {
        const hook = oauthHookMap[provider];
        if (!hook || !providerSupportsOrgConsent(provider)) {
            const errorMsg = `${provider} does not offer organization-wide consent`;
            setError(errorMsg);
            onError?.(errorMsg);
            return;
        }
        setError(null);
        setPlanLimitError(null);
        setConnectingProvider(provider);
        setPendingSelection(null);
        hook.connect(name, scopes || [], { orgConsent: true });
    }, [oauthHookMap, onError]);

    const isConnecting = connectingProvider !== null;

    // Auto-clear a stale connectingProvider when the active hook stops connecting
    // (popup closed) without firing our success/error handlers.
    const activeHookConnecting = connectingProvider
        ? Boolean(oauthHookMap[connectingProvider]?.isConnecting)
        : false;
    useEffect(() => {
        if (!connectingProvider) return;
        if (pendingSelection) return;
        if (!activeHookConnecting) setConnectingProvider(null);
    }, [connectingProvider, pendingSelection, activeHookConnecting]);

    const cancelConnect = useCallback(() => {
        setConnectingProvider(null);
        setPendingSelection(null);
        pendingSelectionResolverRef.current = null;
    }, []);

    const clearError = useCallback(() => {
        setError(null);
        setPlanLimitError(null);
    }, []);

    const resolvePendingSelection = useCallback(async (optionId: string) => {
        const resolve = pendingSelectionResolverRef.current;
        if (!resolve) return;
        setError(null);
        setConnectingProvider(pendingSelection?.provider ?? 'oauth');
        await resolve(optionId);
    }, [pendingSelection?.provider]);

    return {
        connect,
        connectOrgConsent,
        isConnecting,
        connectingProvider,
        error,
        planLimitError,
        clearError,
        pendingSelection,
        resolvePendingSelection,
        cancelConnect,
    };
}
