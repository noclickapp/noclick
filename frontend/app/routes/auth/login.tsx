import { redirect, type ActionFunctionArgs, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Sign In - NoClick',
        description: 'Sign in to your NoClick account.',
        indexable: false,
    });
import { useActionData, Form, Link, useSearchParams, useFetcher, useLoaderData, useNavigate, useNavigation } from 'react-router';
import { requireGuest, createBrowserSupabaseClient } from '~/lib/supabase';
import { authenticate } from '~/lib/auth.server';
import { handleGoogleOAuthAction } from '~/lib/authGoogleAction.server';
import { generateCsrfToken, csrfFailureResponse } from '~/lib/csrf.server';
import { resolveCsrfToken } from '~/lib/csrf';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Label } from '~/components/ui/label';
import { motion, AnimatePresence } from 'framer-motion';
import { AuthLayout } from '~/components/auth/AuthLayout';
import { AgentScaffoldAuthPanel } from '~/components/agents/AgentScaffoldAuthPanel';
import {
    GoogleAuthButton,
    ButtonSpinner,
    LEADING_SPINNER_CLASS,
} from '~/components/auth/authFormShared';
import {
    AuthShellDivider,
    AuthShellPage,
    THESIS_INPUT_CLASS,
    THESIS_PRIMARY_BUTTON_CLASS,
} from '~/components/auth/AuthShell';
import { TurnstileWidget } from '~/components/auth/TurnstileWidget';
import { useState, useEffect } from 'react';
import { Building2 } from 'lucide-react';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

export async function loader({ request }: LoaderFunctionArgs) {
    // Forward requireGuest's headers so a refreshed session is persisted, then
    // add the CSRF cookie alongside it (append, don't overwrite).
    const { headers, env } = await requireGuest(request);
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);
    return json({ csrfToken, env }, { headers });
}

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const provider = formData.get('provider') as string;

    // Get the 'next' parameter for post-login redirect (e.g., MCP OAuth flow)
    const url = new URL(request.url);
    const nextUrl = url.searchParams.get('next');

    // Validate next URL to prevent open redirects - only allow:
    // 1. Relative paths starting with /
    // 2. URLs on the same origin
    // 3. URLs to our backend (localhost with any port for dev, or production backend)
    const getRedirectUrl = () => {
        if (!nextUrl) return '/dashboard';

        try {
            // Check if it's a relative path
            if (nextUrl.startsWith('/') && !nextUrl.startsWith('//')) {
                return nextUrl;
            }

            // Parse as absolute URL
            const parsed = new URL(nextUrl);
            const currentOrigin = new URL(request.url).origin;

            // Allow same origin
            if (parsed.origin === currentOrigin) {
                return nextUrl;
            }

            // Allow localhost URLs (for local dev with backend on different port)
            if (
                parsed.hostname === 'localhost' ||
                parsed.hostname === '127.0.0.1'
            ) {
                return nextUrl;
            }

            // Disallow other external URLs (open redirect protection)
            return '/dashboard';
        } catch {
            return '/dashboard';
        }
    };

    const redirectTo = getRedirectUrl();

    if (provider === 'google') {
        // Shared with the register action; skips CSRF (OAuth state/PKCE covers it).
        return handleGoogleOAuthAction(request);
    }

    // Password login carries credentials, so keep CSRF protection. The check is
    // self-healing: on a stale-session failure it hands back a fresh token+cookie
    // so the next submit works without a page reload (see helper).
    const csrfFailure = await csrfFailureResponse(request, formData);
    if (csrfFailure) return csrfFailure;

    const email = formData.get('email') as string;
    const password = formData.get('password') as string;
    const captchaToken = formData.get('captchaToken') as string;

    const { error, headers } = await authenticate(request, 'login', {
        email,
        password,
        captchaToken,
    });

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    return redirect(redirectTo, { headers });
}

export default function Login() {
    const { env, csrfToken } = useLoaderData() as JsonPayloadOf<typeof loader>;
    const actionData = useActionData() as JsonPayloadOf<typeof action>;
    const navigate = useNavigate();
    const navigation = useNavigation();
    const [searchParams] = useSearchParams();

    // In-flight submit tracking so the pressed button shows a spinner instead of
    // sitting inert (the Google form carries provider=google; the email form
    // carries an email field). Both drive a redirect, so the spinner holds until
    // the page navigates away.
    const submitting = navigation.state !== 'idle';
    const emailPending =
        submitting && navigation.formData?.has('email') === true;
    const [captchaToken, setCaptchaToken] = useState<string>('');
    const [captchaKey, setCaptchaKey] = useState(0);
    const [showSSO, setShowSSO] = useState(false);
    const [ssoSlug, setSsoSlug] = useState('');
    const [handlingTokens, setHandlingTokens] = useState(false);
    const ssoFetcher = useFetcher();

    // After a stale-session (CSRF) error the action returns a refreshed token
    // matching a freshly-set cookie. Prefer it so the form re-submits cleanly
    // instead of replaying the same expired token until the user reloads.
    const freshCsrfToken = resolveCsrfToken(csrfToken, actionData);

    // Preserve redirect URL for navigation between auth pages
    const nextUrl = searchParams.get('next');
    const nextParam = nextUrl ? `?next=${encodeURIComponent(nextUrl)}` : '';

    // Present when the visitor arrived from an /agents SEO "open this agent" CTA:
    // swaps the right panel for the live scaffold preview and makes the copy about
    // launching that specific agent instead of the generic "welcome back".
    const agentName = searchParams.get('agent');
    const registerParams = nextParam
        ? `${nextParam}${agentName ? `&agent=${encodeURIComponent(agentName)}` : ''}`
        : agentName
          ? `?agent=${encodeURIComponent(agentName)}`
          : '';

    // Informational (non-error) notice, e.g. the user cancelled the Google consent screen
    // and the auth callback sent them back here instead of the error page.
    const notice =
        searchParams.get('notice') === 'oauth_cancelled'
            ? "Sign-in was cancelled before completing. You can try again whenever you're ready."
            : null;

    // Keep cancellations measurable alongside error-page reasons (same event, one dashboard).
    const { logActivity } = useAnalytics();
    useEffect(() => {
        if (notice) {
            logActivity(EVENTS.AUTH_ERROR_PAGE_SHOWN, {
                reason: 'oauth_cancelled',
                surface: 'login_notice',
            });
        }
    }, [notice, logActivity]);

    // Handle IdP-initiated SSO tokens in URL fragment
    // Supabase redirects here with #access_token=... when RelayState points to /auth/login
    useEffect(() => {
        const handleImplicitFlow = async () => {
            const hash = window.location.hash;

            if (hash && hash.includes('access_token=')) {
                setHandlingTokens(true);
                const params = new URLSearchParams(hash.substring(1));
                const accessToken = params.get('access_token');
                const refreshToken = params.get('refresh_token');

                if (accessToken && refreshToken) {
                    const supabase = createBrowserSupabaseClient(env);
                    const { error } = await supabase.auth.setSession({
                        access_token: accessToken,
                        refresh_token: refreshToken,
                    });

                    if (!error) {
                        // Redirect to dashboard or the next URL
                        const redirectTo = nextUrl || '/dashboard';
                        navigate(redirectTo, { replace: true });
                        return;
                    }
                }
                setHandlingTokens(false);
            }
        };

        handleImplicitFlow();
    }, [env, navigate, nextUrl]);

    // Check for SSO hint in URL
    useEffect(() => {
        const orgHint = searchParams.get('org');
        if (orgHint) {
            setSsoSlug(orgHint);
            setShowSSO(true);
        }
    }, [searchParams]);

    // Reset captcha after a real auth attempt so its single-use token isn't
    // replayed. A CSRF/session error (which carries a refreshed csrfToken) never
    // reached captcha verification, so we keep the token there — otherwise the
    // Sign In button would be stuck disabled and the user couldn't retry.
    // NOTE: This must be before any early returns to avoid React hooks violation
    useEffect(() => {
        if (actionData && actionData.error && !('csrfToken' in actionData)) {
            setCaptchaToken('');
            setCaptchaKey((prev) => prev + 1); // Force captcha widget remount
        }
    }, [actionData]);

    // Show loading state while handling SSO tokens
    if (handlingTokens) {
        return (
            <AuthLayout>
                <div className="flex min-h-[400px] items-center justify-center">
                    <div className="text-center">
                        <div className="animate-spin h-8 w-8 border-4 border-foreground border-t-transparent rounded-full mx-auto"></div>
                        <p className="mt-4 text-muted-foreground">
                            Completing sign in...
                        </p>
                    </div>
                </div>
            </AuthLayout>
        );
    }

    // Handle SSO form submission
    const handleSSOSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!ssoSlug.trim()) return;
        ssoFetcher.submit(
            { slug: ssoSlug.trim().toLowerCase() },
            { method: 'post', action: `/auth/sso${nextParam}` }
        );
    };

    const ssoError = (ssoFetcher.data as { error?: string } | undefined)?.error;

    return (
        <AuthLayout
            rightPanel={
                agentName ? (
                    <AgentScaffoldAuthPanel agentName={agentName} />
                ) : undefined
            }
        >
            <AuthShellPage
                eyebrow={showSSO ? 'Enterprise / SSO' : undefined}
                title={showSSO ? 'Your workspace.' : 'Welcome back.'}
                mutedTitle={
                    showSSO
                        ? 'One secure sign-in.'
                        : agentName
                          ? 'Your agent is waiting.'
                          : undefined
                }
                description={
                    showSSO
                        ? "Continue with your company's identity provider."
                        : agentName
                          ? `${agentName} is wired up. Sign in to finish it.`
                          : 'Sign in to return to your workspace and pick up where you left off.'
                }
                footer={
                    showSSO ? (
                        <button
                            type="button"
                            onClick={() => {
                                setShowSSO(false);
                                setSsoSlug('');
                            }}
                            className="font-medium text-foreground transition-opacity hover:opacity-70"
                        >
                            ← Back to sign in
                        </button>
                    ) : (
                        <>
                            <span>New to NoClick?</span>
                            <Link
                                to={`/auth/register${registerParams}`}
                                className="font-medium text-foreground transition-opacity hover:opacity-70"
                            >
                                Create account
                            </Link>
                            <span>·</span>
                            <button
                                type="button"
                                onClick={() => setShowSSO(true)}
                                className="transition-colors hover:text-foreground"
                            >
                                Enterprise SSO
                            </button>
                        </>
                    )
                }
            >
                <div data-testid="auth-shell-form">
                    <AnimatePresence mode="wait">
                        {!showSSO ? (
                            <motion.div
                                key="main-login"
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0, x: -20 }}
                                transition={{ duration: 0.2 }}
                            >
                                {notice && !actionData?.error && (
                                    <div className="mb-6 p-4 text-muted-foreground dark:text-zinc-300 bg-zinc-500/10 rounded-lg text-sm">
                                        {notice}
                                    </div>
                                )}

                                {actionData?.error && (
                                    <div className="mb-6 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg text-sm">
                                        {actionData.error}
                                    </div>
                                )}

                                <GoogleAuthButton label="Continue with Google" />
                                <AuthShellDivider />

                                <Form method="post" className="space-y-4">
                                    <input
                                        type="hidden"
                                        name="csrf_token"
                                        value={freshCsrfToken}
                                    />
                                    <div>
                                        <Label
                                            htmlFor="email"
                                            className="mb-2 block text-xs font-medium text-muted-foreground"
                                        >
                                            Email
                                        </Label>
                                        <Input
                                            id="email"
                                            name="email"
                                            type="email"
                                            required
                                            placeholder="you@company.com"
                                            className={THESIS_INPUT_CLASS}
                                        />
                                    </div>

                                    <div>
                                        <div className="mb-2 flex items-center justify-between">
                                            <Label
                                                htmlFor="password"
                                                className="block text-xs font-medium text-muted-foreground"
                                            >
                                                Password
                                            </Label>
                                            <Link
                                                to="/auth/forgot-password"
                                                className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                                            >
                                                Forgot password?
                                            </Link>
                                        </div>
                                        <Input
                                            id="password"
                                            name="password"
                                            type="password"
                                            required
                                            placeholder="Your password"
                                            className={THESIS_INPUT_CLASS}
                                        />
                                    </div>

                                    <TurnstileWidget
                                        key={captchaKey}
                                        onSuccess={(token) =>
                                            setCaptchaToken(token)
                                        }
                                        onError={() => setCaptchaToken('')}
                                    />

                                    <input
                                        type="hidden"
                                        name="captchaToken"
                                        value={captchaToken}
                                    />

                                    <Button
                                        type="submit"
                                        disabled={!captchaToken || submitting}
                                        className={THESIS_PRIMARY_BUTTON_CLASS}
                                    >
                                        {emailPending && (
                                            <ButtonSpinner
                                                className={
                                                    LEADING_SPINNER_CLASS
                                                }
                                            />
                                        )}
                                        Sign in
                                    </Button>
                                </Form>
                            </motion.div>
                        ) : (
                            <motion.div
                                key="sso-login"
                                initial={{ opacity: 0, x: 20 }}
                                animate={{ opacity: 1, x: 0 }}
                                exit={{ opacity: 0, x: 20 }}
                                transition={{ duration: 0.2 }}
                            >
                                <div className="mb-6 flex items-center gap-3">
                                    <div className="w-10 h-10 rounded-full bg-secondary flex items-center justify-center">
                                        <Building2 className="w-5 h-5 text-muted-foreground" />
                                    </div>
                                    <div>
                                        <h3 className="text-base font-medium text-foreground">
                                            Enterprise SSO
                                        </h3>
                                        <p className="text-sm text-muted-foreground/70 dark:text-zinc-500">
                                            Sign in with your company&apos;s
                                            identity provider
                                        </p>
                                    </div>
                                </div>

                                {ssoError && (
                                    <div className="mb-5 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg text-sm">
                                        {ssoError}
                                    </div>
                                )}

                                <form
                                    onSubmit={handleSSOSubmit}
                                    className="space-y-5"
                                >
                                    <div>
                                        <Label
                                            htmlFor="sso-slug"
                                            className="mb-2 block text-xs font-medium text-muted-foreground"
                                        >
                                            Organization
                                        </Label>
                                        <Input
                                            id="sso-slug"
                                            type="text"
                                            required
                                            value={ssoSlug}
                                            onChange={(e) =>
                                                setSsoSlug(
                                                    e.target.value
                                                        .toLowerCase()
                                                        .replace(
                                                            /[^a-z0-9-]/g,
                                                            ''
                                                        )
                                                )
                                            }
                                            placeholder="acme-corp"
                                            className={THESIS_INPUT_CLASS}
                                        />
                                        <p className="mt-2 text-sm text-muted-foreground/70 dark:text-zinc-500">
                                            Your organization&apos;s NoClick
                                            workspace identifier
                                        </p>
                                    </div>

                                    <Button
                                        type="submit"
                                        disabled={
                                            !ssoSlug.trim() ||
                                            ssoFetcher.state !== 'idle'
                                        }
                                        className={THESIS_PRIMARY_BUTTON_CLASS}
                                    >
                                        {ssoFetcher.state !== 'idle' && (
                                            <ButtonSpinner
                                                className={
                                                    LEADING_SPINNER_CLASS
                                                }
                                            />
                                        )}
                                        Continue with SSO
                                    </Button>
                                </form>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </AuthShellPage>
        </AuthLayout>
    );
}
