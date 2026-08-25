/**
 * Workflow invite-link landing route (/i/<token>).
 *
 * Shown to logged-out visitors, so it carries the real auth surface (Google +
 * email/password sign-up & sign-in + Cloudflare Turnstile) embedded in the
 * page (InviteLandingView / InviteAuthPanel). Auth posts to this route's action
 * with next=/i/<token>, so the visitor bounces back here authenticated, where we
 * stash the token and hand off to the dashboard — WorkflowBrowser then redeems
 * it (adds a share row) and opens the SAME shared flow (no fork).
 */

import { redirect, type ActionFunctionArgs, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useEffect, type ReactNode } from 'react';
import { useLoaderData, useNavigate, Link } from 'react-router';
import { createPublicLoaderData, csrfFailureResponse } from '~/lib/csrf.server';
import { authenticate } from '~/lib/auth.server';
import { buildSeoMeta } from '~/lib/seo';
import { PENDING_INVITE_KEY } from '~/lib/inviteLink';
import { InviteLandingView } from '~/components/invite/InviteLandingView';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import { LogoMark } from '~/components/shared/LogoMark';

interface InvitePreview {
    workflow_id: string;
    workflow_name: string | null;
    owner_name: string | null;
    owner_avatar_url: string | null;
}

export const meta: MetaFunction = ({ data }) => {
    const typedData = data as JsonPayloadOf<typeof loader> | undefined;
    const owner = typedData?.preview?.owner_name || 'Someone';
    return buildSeoMeta({
        title: 'Join a workflow - NoClick',
        description: `${owner} invited you to build a workflow together on NoClick.`,
        indexable: false,
    });
};

export async function loader({ params, request }: LoaderFunctionArgs) {
    const token = params.token;
    if (!token) {
        throw new Response('Invite token is required', { status: 400 });
    }

    const backendUrl = process.env.VITE_API_URL || 'http://localhost:8000';

    // Auth status + CSRF token (+ forwards a rotated session cookie / sets the
    // CSRF cookie via headers — must be returned).
    const authResponse = await createPublicLoaderData(request);
    const baseData = (await authResponse.json()) as {
        isAuthenticated: boolean;
        csrfToken: string;
    };
    const headers = authResponse.headers;

    let preview: InvitePreview | null = null;
    try {
        const response = await fetch(
            `${backendUrl}/api/public/invite/${encodeURIComponent(token)}`,
            {
                headers: { Accept: 'application/json' },
            }
        );
        if (response.ok) {
            preview = await response.json();
        }
    } catch (e) {
        console.error('Failed to load invite preview:', e);
    }

    return json({ ...baseData, token, preview }, { headers });
}

export async function action({ request, params }: ActionFunctionArgs) {
    const token = params.token;
    // After auth, bounce back here so the (now authenticated) loader can redeem.
    const nextUrl = token ? `/i/${token}` : '/dashboard';

    const formData = await request.formData();
    const provider = formData.get('provider');

    // Google OAuth — deliberately skips the app CSRF check (OAuth state/PKCE
    // protects it; gating it breaks on stale CSRF cookies), matching /auth/login.
    if (provider === 'google') {
        const { error, authUrl, headers } = await authenticate(
            request,
            'google',
            undefined,
            nextUrl
        );
        if (error || !authUrl) {
            return json(
                { error: error || 'Failed to start Google sign-in' },
                { status: 400, headers }
            );
        }
        return redirect(authUrl, { headers });
    }

    // Credential flows carry the double-submit CSRF token (self-healing). Pass the
    // already-parsed formData — the request body is a one-shot stream, so cloning
    // it here after request.formData() above would throw "unusable".
    const csrfFailure = await csrfFailureResponse(request, formData);
    if (csrfFailure) return csrfFailure;

    const email = formData.get('email') as string;
    const password = formData.get('password') as string;
    const captchaToken = formData.get('captchaToken') as string;

    if (formData.get('intent') === 'register') {
        const confirmPassword = formData.get('confirmPassword') as string;
        const { error, success, headers } = await authenticate(
            request,
            'register',
            { email, password, confirmPassword, captchaToken },
            nextUrl
        );
        if (error) return json({ error }, { status: 400, headers });
        return json({ success }, { headers });
    }

    // Sign in — immediate session; redirect back here to redeem the invite.
    const { error, headers } = await authenticate(request, 'login', {
        email,
        password,
        captchaToken,
    });
    if (error) return json({ error }, { status: 400, headers });
    return redirect(nextUrl, { headers });
}

function DarkScreen({ children }: { children: ReactNode }) {
    return (
        <div className="flex min-h-screen w-full items-center justify-center bg-background dark:bg-zinc-950 px-6 text-center font-sans text-foreground">
            <div className="max-w-sm">{children}</div>
        </div>
    );
}

export default function InviteLandingPage() {
    const { isAuthenticated, token, preview, csrfToken } =
        useLoaderData() as JsonPayloadOf<typeof loader>;
    const navigate = useNavigate();
    const { logActivity } = useAnalytics();

    // Top of the recipient funnel: a logged-out visitor landed on a valid invite
    // (captured anonymously; PostHog aliases to the user if they sign up).
    useEffect(() => {
        if (preview && !isAuthenticated) {
            logActivity(EVENTS.INVITE_LANDING_VIEWED, {
                workflow_id: preview.workflow_id,
            });
        }
    }, [preview, isAuthenticated, logActivity]);

    // Authenticated: stash the token and hand off to the dashboard, which redeems
    // it once the socket is up and opens the shared flow.
    useEffect(() => {
        if (isAuthenticated && preview) {
            sessionStorage.setItem(PENDING_INVITE_KEY, token);
            navigate('/dashboard?tab=workflows', { replace: true });
        }
    }, [isAuthenticated, preview, token, navigate]);

    if (!preview) {
        return (
            <DarkScreen>
                <LogoMark className="mx-auto mb-5 h-8 w-8" />
                <h1 className="mb-2 text-2xl font-semibold text-foreground">
                    Invite unavailable
                </h1>
                <p className="mb-7 text-[15px] text-muted-foreground">
                    This invite link is no longer valid or has been turned off.
                </p>
                <Link
                    to="/"
                    className="inline-flex h-11 items-center justify-center rounded-xl bg-primary px-7 text-[14px] font-semibold text-primary-foreground"
                >
                    Go to NoClick
                </Link>
            </DarkScreen>
        );
    }

    if (isAuthenticated) {
        return (
            <DarkScreen>
                <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-foreground border-t-transparent" />
                <p className="mt-4 text-muted-foreground">
                    Joining the workflow…
                </p>
            </DarkScreen>
        );
    }

    return (
        <InviteLandingView
            ownerName={preview.owner_name || 'Someone'}
            ownerAvatar={preview.owner_avatar_url || ''}
            workflowName={preview.workflow_name || 'a workflow'}
            csrfToken={csrfToken}
        />
    );
}
