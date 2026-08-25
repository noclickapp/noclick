import Dashboard from '~/components/Dashboard';
import { OnboardingQuestionnaire } from '~/components/onboarding/OnboardingQuestionnaire';
import { useLoaderData } from 'react-router';
import type { ShouldRevalidateFunctionArgs } from 'react-router';
import { redirect, type LoaderFunctionArgs, type ActionFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { buildSeoMeta } from '~/lib/seo';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import { setNodeIconData } from '~/lib/nodeIconRegistry';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Dashboard - NoClick',
        description: 'Your NoClick workspace.',
        indexable: false,
    });
import { requireAuth , signOut , createBrowserSupabaseClient } from '~/lib/supabase';
import { useEffect, useState } from 'react';
import { useSocketTokenRefresh } from '~/hooks/useSocketTokenRefresh';
import { useValtioState } from '~/hooks/useValtioState';
import { useMCPNavigation } from '~/hooks/useMCPNavigation';
import { useEventRelay } from '~/hooks/useEventRelay';
import { useShareNotifications } from '~/hooks/useShareNotifications';
import { SCAFFOLD_DATA_KEY } from '~/lib/agentScaffold';
import { isOnboardingPersisted, markOnboardingPersisted } from '~/lib/onboardingLocal';
import { isLocalEdition } from '~/lib/edition';

export async function loader({ request }: LoaderFunctionArgs) {
    const { user, session: authSession, headers: authHeaders } = await requireAuth(request);
    // Use headers from requireAuth to propagate any token refresh cookies
    const headers = authHeaders;
    // Extract subscription_tier, personal_subscription_tier, personal_workspace_org_id, and onboarding_completed from JWT claims
    let subscriptionTier: 'free' | 'pro' | 'team' | 'enterprise' = 'free';
    let personalSubscriptionTier: 'free' | 'pro' | 'team' | 'enterprise' = 'free';
    let personalWorkspaceOrgId: string | null = null;
    let onboardingCompleted = false;
    try {
        if (authSession?.access_token) {
            // Decode JWT payload (middle part of the token)
            const payload = JSON.parse(
                Buffer.from(authSession.access_token.split('.')[1], 'base64').toString()
            );
            subscriptionTier = payload.subscription_tier || 'free';
            personalSubscriptionTier = payload.personal_subscription_tier || payload.subscription_tier || 'free';
            personalWorkspaceOrgId = payload.personal_workspace_org_id || null;
            onboardingCompleted = payload.onboarding_completed || false;
        }
    } catch (error) {
        console.error('Failed to decode JWT claims:', error);
        // Fallback to defaults if JWT decode fails
        subscriptionTier = 'free';
        personalSubscriptionTier = 'free';
        personalWorkspaceOrgId = null;
        onboardingCompleted = false;
    }

    return json({
        env: {
            SUPABASE_URL: process.env.SUPABASE_URL!,
            SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY!,
        },
        user,
        subscriptionTier,
        personalSubscriptionTier,
        personalWorkspaceOrgId,
        onboardingCompleted,
        // Pre-rendered node brand icons (label + iconColor + iconHtml) for the
        // authed app's always-mounted icon surfaces (command palette, list rows,
        // chat, credential icons) — lets them render icons WITHOUT importing the
        // heavy node registry (which now ships only with the lazy editor).
        nodeIconData: getAllSerializedNodeMeta(),
    }, {
        headers
    });
}

export async function action({ request }: ActionFunctionArgs) {
    const headers = await signOut(request);
    return redirect('/auth/login', { headers });
}

// Prevent automatic loader revalidation on child-route navigation.
// Dashboard loader data (auth and instance claims) only needs to load once.
// Form submissions and explicit same-URL refreshes may re-run it.
export function shouldRevalidate({
    formAction,
    currentUrl,
    nextUrl,
    defaultShouldRevalidate,
}: ShouldRevalidateFunctionArgs) {
    if (formAction) return defaultShouldRevalidate;
    // An explicit same-URL refresh is distinct from child-route navigation.
    if (currentUrl.toString() === nextUrl.toString()) {
        return defaultShouldRevalidate;
    }
    return false;
}

export default function DashboardRoute() {
    const { env, user, subscriptionTier, personalSubscriptionTier, personalWorkspaceOrgId, onboardingCompleted, nodeIconData } = useLoaderData() as JsonPayloadOf<typeof loader>;
    // Populate the node-icon singleton before any child (command palette, list
    // rows, chat, credential icons) renders, so they can resolve brand icons
    // without importing the node registry. Idempotent; safe to call each render.
    setNodeIconData(nodeIconData);
    // Optimistic state for instant dashboard reveal after onboarding submit
    const [optimisticOnboardingComplete, setOptimisticOnboardingComplete] = useState(false);
    // Invite joiners skip onboarding: redeeming the invite (WorkflowBrowser)
    // creates their onboarding row server-side, so suppress the questionnaire
    // while that's pending. Lazy-read once — invite users arrive via client
    // navigation from /i/<token>, so sessionStorage is available (no SSR flash).
    const [skipInviteOnboarding, setSkipInviteOnboarding] = useState(
        () => typeof window !== 'undefined' && !!sessionStorage.getItem('noclick_pending_invite'),
    );
    // Scaffold arrivals (the /agents, /mcp, and connect "select" buttons) carry an
    // explicit intent — the user already picked the agent/mcp/connection to open.
    // Skip the onboarding questionnaire so they land straight on that workflow
    // instead of being asked build-type questions (and, if they answer "Website",
    // misrouted to the interface tab where their agent/mcp isn't visible). The
    // scaffold blob sits in sessionStorage from the marketing page through sign-in
    // until WorkflowBrowser materializes it, so it's present on this first render.
    // This flag only suppresses onboarding for THIS mount; materializing the scaffold
    // also persists the skip server-side (onboarding:skip → onboarding_completed
    // claim) so it survives future remounts and later sessions — otherwise the
    // questionnaire re-appeared once the sessionStorage flag was consumed.
    const [skipScaffoldOnboarding] = useState(
        () => typeof window !== 'undefined' && !!sessionStorage.getItem(SCAFFOLD_DATA_KEY),
    );
    // Durable backstop for stale JWTs: after a crash + re-login the token can
    // predate the user's onboarding row, which would re-show the questionnaire
    // (and re-run its post-onboarding auto-create) on an onboarded user.
    const [onboardingPersistedLocally] = useState(
        () => typeof window !== 'undefined' && isOnboardingPersisted(user.id),
    );
    // When the redeem reports it onboarded the joiner, refresh the JWT so the
    // onboarding_completed claim flips for the rest of the session. If the redeem
    // FAILS, un-suppress onboarding — the server never created the joiner's
    // onboarding row, so a genuinely un-onboarded user must still see the
    // questionnaire instead of being silently locked out of it for the session.
    useEffect(() => {
        const onRedeemed = () => {
            setOptimisticOnboardingComplete(true);
            markOnboardingPersisted(user.id);
            createBrowserSupabaseClient(env).auth.refreshSession().catch(() => {});
        };
        const onFailed = () => setSkipInviteOnboarding(false);
        document.addEventListener('noclick:invite:onboarded', onRedeemed);
        // Scaffold (agent-SEO) arrivals persist their onboarding skip server-side
        // once materialized; refresh the JWT so the flipped onboarding_completed
        // claim survives future dashboard remounts (same handler as invite joiners).
        document.addEventListener('noclick:onboarding:persisted', onRedeemed);
        document.addEventListener('noclick:invite:onboard-failed', onFailed);
        return () => {
            document.removeEventListener('noclick:invite:onboarded', onRedeemed);
            document.removeEventListener('noclick:onboarding:persisted', onRedeemed);
            document.removeEventListener('noclick:invite:onboard-failed', onFailed);
        };
    }, [env, user.id]);

    // Connect to Event Relay for cross-container real-time events (webhooks, cron, etc.)
    useEventRelay({ userId: user.id });


    // Store subscription tier in global Valtio state for access across all components
    // subscription_tier = effective tier (org tier when in org, personal otherwise)
    // personal_subscription_tier = always the personal tier from user_billing
    const [, setGlobalSubscriptionTier] = useValtioState<'free' | 'pro' | 'team' | 'enterprise'>(
        'global',
        'subscription_tier',
        'free'
    );
    const [, setGlobalPersonalTier] = useValtioState<'free' | 'pro' | 'team' | 'enterprise'>(
        'global',
        'personal_subscription_tier',
        'free'
    );
    const [, setGlobalPersonalWsOrgId] = useValtioState<string | null>(
        'global',
        'personal_workspace_org_id',
        null
    );

    // Update global state whenever loader data changes
    useEffect(() => {
        setGlobalSubscriptionTier(subscriptionTier);
    }, [subscriptionTier, setGlobalSubscriptionTier]);
    useEffect(() => {
        setGlobalPersonalTier(personalSubscriptionTier);
    }, [personalSubscriptionTier, setGlobalPersonalTier]);
    useEffect(() => {
        setGlobalPersonalWsOrgId(personalWorkspaceOrgId);
    }, [personalWorkspaceOrgId, setGlobalPersonalWsOrgId]);

    // Handle token refreshes and update socket authentication
    useSocketTokenRefresh();

    // Handle MCP navigation requests (open_workflow, create_workflow)
    useMCPNavigation();

    // Listen for share notifications and display toasts
    useShareNotifications();

    // Request notification permission on dashboard load
    useEffect(() => {
        const requestNotificationPermission = async () => {
            if ('Notification' in window && Notification.permission === 'default') {
                // Wait a bit after page load to avoid being too aggressive
                setTimeout(async () => {
                    await Notification.requestPermission();
                }, 1000);
            }
        };

        requestNotificationPermission();
    }, []);

    // Show onboarding questionnaire if not completed (check server state, optimistic
    // state, the invite-joiner suppression — invite redemption onboards them — and
    // the scaffold suppression — agent/mcp/connect "select" arrivals open their
    // pre-built workflow instead of onboarding).
    // The self-hosted edition skips it outright: the answers feed hosted
    // personalization, so asking is pure friction between install and canvas.
    if (!isLocalEdition() && !onboardingCompleted && !optimisticOnboardingComplete && !skipInviteOnboarding && !skipScaffoldOnboarding && !onboardingPersistedLocally) {
        return (
            <OnboardingQuestionnaire
                env={env}
                onComplete={() => {
                    setOptimisticOnboardingComplete(true);
                    markOnboardingPersisted(user.id);
                }}
            />
        );
    }

    return (
        <Dashboard
            user={{
                email: user.email || '',
                avatar_url: user.user_metadata?.avatar_url,
                created_at: user.created_at,
                subscription_tier: subscriptionTier === 'team' ? 'plus' : subscriptionTier,
            }}
            valtio_path={'dashboard'}
        />
    );
}
