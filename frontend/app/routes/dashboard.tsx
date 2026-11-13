import Dashboard from '~/components/Dashboard';
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
import { requireAuth , signOut } from '~/lib/supabase';
import { useEffect } from 'react';
import { useSocketTokenRefresh } from '~/hooks/useSocketTokenRefresh';
import { useValtioState } from '~/hooks/useValtioState';
import { useMCPNavigation } from '~/hooks/useMCPNavigation';
import { useEventRelay } from '~/hooks/useEventRelay';
import { useShareNotifications } from '~/hooks/useShareNotifications';

export async function loader({ request }: LoaderFunctionArgs) {
    const { user, session: authSession, headers: authHeaders } = await requireAuth(request);
    // Use headers from requireAuth to propagate any token refresh cookies
    const headers = authHeaders;
    // Extract subscription_tier, personal_subscription_tier and personal_workspace_org_id from JWT claims
    let subscriptionTier: 'free' | 'pro' | 'team' | 'enterprise' = 'free';
    let personalSubscriptionTier: 'free' | 'pro' | 'team' | 'enterprise' = 'free';
    let personalWorkspaceOrgId: string | null = null;
    try {
        if (authSession?.access_token) {
            // Decode JWT payload (middle part of the token)
            const payload = JSON.parse(
                Buffer.from(authSession.access_token.split('.')[1], 'base64').toString()
            );
            subscriptionTier = payload.subscription_tier || 'free';
            personalSubscriptionTier = payload.personal_subscription_tier || payload.subscription_tier || 'free';
            personalWorkspaceOrgId = payload.personal_workspace_org_id || null;
        }
    } catch (error) {
        console.error('Failed to decode JWT claims:', error);
        // Fallback to defaults if JWT decode fails
        subscriptionTier = 'free';
        personalSubscriptionTier = 'free';
        personalWorkspaceOrgId = null;
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
    const { user, subscriptionTier, personalSubscriptionTier, personalWorkspaceOrgId, nodeIconData } = useLoaderData() as JsonPayloadOf<typeof loader>;
    // Populate the node-icon singleton before any child (command palette, list
    // rows, chat, credential icons) renders, so they can resolve brand icons
    // without importing the node registry. Idempotent; safe to call each render.
    setNodeIconData(nodeIconData);
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
