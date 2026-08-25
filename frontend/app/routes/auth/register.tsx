import { type ActionFunctionArgs, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Sign Up - NoClick',
        description: 'Create your free NoClick account.',
        indexable: false,
    });
import { useActionData, useLoaderData, Form, Link, useSearchParams, useNavigation } from 'react-router';
import { requireGuest } from '~/lib/supabase';
import { authenticate } from '~/lib/auth.server';
import { handleGoogleOAuthAction } from '~/lib/authGoogleAction.server';
import { generateCsrfToken, csrfFailureResponse } from '~/lib/csrf.server';
import { resolveCsrfToken } from '~/lib/csrf';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Label } from '~/components/ui/label';
import { AuthLayout } from '~/components/auth/AuthLayout';
import { AgentScaffoldAuthPanel } from '~/components/agents/AgentScaffoldAuthPanel';
import {
    GoogleAuthButton,
    ButtonSpinner,
    GoogleIcon,
    LEADING_SPINNER_CLASS,
} from '~/components/auth/authFormShared';
import {
    AuthShellDivider,
    AuthShellPage,
    THESIS_INPUT_CLASS,
    THESIS_PRIMARY_BUTTON_CLASS,
} from '~/components/auth/AuthShell';
import { TurnstileWidget } from '~/components/auth/TurnstileWidget';
import { useState, useEffect, useRef } from 'react';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';

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

    if (provider === 'google') {
        // Shared with the login action; skips CSRF (OAuth state/PKCE covers it).
        return handleGoogleOAuthAction(request);
    }

    // Self-healing CSRF check for the credential path: hands back a fresh
    // token+cookie on a stale-session failure so the next submit works without a
    // page reload. Pass the already-read formData so the body isn't consumed twice.
    const csrfFailure = await csrfFailureResponse(request, formData);
    if (csrfFailure) return csrfFailure;

    const email = formData.get('email') as string;
    const password = formData.get('password') as string;
    const confirmPassword = formData.get('confirmPassword') as string;
    const username = formData.get('username') as string;
    const captchaToken = formData.get('captchaToken') as string;

    // Get the 'next' parameter for post-signup redirect
    const nextUrl = new URL(request.url).searchParams.get('next');

    const { error, success, headers } = await authenticate(
        request,
        'register',
        {
            email,
            password,
            confirmPassword,
            username,
            captchaToken,
        },
        nextUrl || undefined
    );

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    return json({ success }, { headers });
}

export default function Register() {
    const { csrfToken } = useLoaderData() as JsonPayloadOf<typeof loader>;
    const actionData = useActionData() as JsonPayloadOf<typeof action>;
    // Prefer the token a stale-session error hands back so retry self-heals.
    const freshCsrfToken = resolveCsrfToken(csrfToken, actionData);
    const [searchParams] = useSearchParams();
    const navigation = useNavigation();
    const [captchaToken, setCaptchaToken] = useState<string>('');
    const [captchaKey, setCaptchaKey] = useState(0);

    // In-flight submit tracking so the pressed button shows a spinner. The email
    // form carries an email field; the Google form (provider=google) doesn't.
    const submitting = navigation.state !== 'idle';
    const emailPending =
        submitting && navigation.formData?.has('email') === true;

    // Preserve redirect URL for navigation between auth pages
    const nextUrl = searchParams.get('next');
    const nextParam = nextUrl ? `?next=${encodeURIComponent(nextUrl)}` : '';

    // Present when the visitor arrived from an /agents SEO "open this agent" CTA:
    // swaps the right panel for the live scaffold preview and makes the copy about
    // launching that specific agent. Carried onto the "Sign in" link too.
    const agentName = searchParams.get('agent');
    const loginParams = nextParam
        ? `${nextParam}${agentName ? `&agent=${encodeURIComponent(agentName)}` : ''}`
        : agentName
          ? `?agent=${encodeURIComponent(agentName)}`
          : '';

    // A/B (auto-google-cta test variant): the /agents CTA can land here with
    // ?google=auto to jump straight to Google OAuth (the ~92%-of-signups path),
    // keeping the email form one browser-Back away. Strip the flag from THIS
    // history entry before redirecting so Back returns to the email form instead
    // of bouncing into Google again; the submit is a native document POST
    // (reloadDocument) so Back restores a clean GET of this page.
    const autoGoogle = searchParams.get('google') === 'auto';
    const autoGoogleFormRef = useRef<HTMLFormElement>(null);
    useEffect(() => {
        if (!autoGoogle) return;
        const url = new URL(window.location.href);
        url.searchParams.delete('google');
        window.history.replaceState(
            window.history.state,
            '',
            url.pathname + url.search
        );
        const form = autoGoogleFormRef.current;
        if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Reset captcha after a real submission attempt. A stale-session (CSRF)
    // error carries a refreshed csrfToken and never reached captcha verification,
    // so keep the token there — otherwise the button would be stuck disabled and
    // the user couldn't retry.
    useEffect(() => {
        if (actionData && !('csrfToken' in actionData)) {
            setCaptchaToken('');
            setCaptchaKey((prev) => prev + 1); // Force captcha widget remount
        }
    }, [actionData]);

    // Fire analytics once per successful signup, mirroring AuthModal: the client-side
    // event carries the signup browser context (the server mirror only knows the user
    // id). The localStorage marker stops dashboard.tsx double-firing after the user
    // lands from the verification email.
    const { logActivity } = useAnalytics();
    const signupCapturedRef = useRef(false);
    useEffect(() => {
        if (
            actionData &&
            'success' in actionData &&
            actionData.success &&
            !signupCapturedRef.current
        ) {
            signupCapturedRef.current = true;
            try {
                localStorage.setItem('pc:signed_up_fired:email', '1');
            } catch {
                /* storage unavailable */
            }
            logActivity(EVENTS.USER_SIGNED_UP, { auth_method: 'email' });
        }
    }, [actionData, logActivity]);

    return (
        <AuthLayout
            rightPanel={
                agentName ? (
                    <AgentScaffoldAuthPanel agentName={agentName} />
                ) : undefined
            }
        >
            {/* google=auto is a pass-through to Google OAuth — cover the form
                for the beat before the auto-submit navigates so the hop reads
                as one motion. Back from Google returns a clean GET (flag
                stripped), so the cover never shows again. */}
            {autoGoogle ? (
                <div className="fixed inset-0 z-[90] flex flex-col items-center justify-center gap-6 bg-background">
                    <ThinkingOrb
                        state="searching"
                        size={64}
                        aria-label=""
                        style={{ width: 28, height: 28 }}
                    />
                    <span className="inline-flex items-center gap-2.5 text-[14px] text-foreground/60">
                        <GoogleIcon />
                        Taking you to Google
                    </span>
                </div>
            ) : null}
            <AuthShellPage
                eyebrow={agentName ? 'Agent launch / 01' : 'Account / 01'}
                title="Build an agent."
                mutedTitle="Then let it run."
                description={
                    agentName
                        ? `${agentName} is wired up. Create your workspace to finish it.`
                        : 'Create your workspace and give your next operation a place to live.'
                }
                footer={
                    <>
                        <span>Already have an account?</span>
                        <Link
                            to={`/auth/login${loginParams}`}
                            className="font-medium text-foreground transition-opacity hover:opacity-70"
                        >
                            Sign in
                        </Link>
                    </>
                }
            >
                <div data-testid="auth-shell-form">
                    {/* Auto-Google (A/B test variant): native document POST so browser-Back
                        restores a clean GET of this page; action carries `next` so the
                        post-auth redirect still lands on the stashed scaffold. */}
                    {autoGoogle && (
                        <Form
                            method="post"
                            reloadDocument
                            ref={autoGoogleFormRef}
                            action={`/auth/register?next=${encodeURIComponent(nextUrl || '/dashboard')}`}
                            className="hidden"
                        >
                            <input
                                type="hidden"
                                name="provider"
                                value="google"
                            />
                        </Form>
                    )}

                    {actionData &&
                        'error' in actionData &&
                        actionData.error && (
                            <div className="mb-6 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg text-sm">
                                {actionData.error}
                            </div>
                        )}

                    {actionData &&
                        'success' in actionData &&
                        actionData.success && (
                            <div className="mb-6 p-4 text-green-600 dark:text-green-400 bg-green-500/10 rounded-lg text-sm">
                                {actionData.success}
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
                            <Label
                                htmlFor="password"
                                className="mb-2 block text-xs font-medium text-muted-foreground"
                            >
                                Password
                            </Label>
                            <Input
                                id="password"
                                name="password"
                                type="password"
                                required
                                placeholder="At least 8 characters"
                                className={THESIS_INPUT_CLASS}
                            />
                        </div>

                        <div>
                            <Label
                                htmlFor="confirmPassword"
                                className="mb-2 block text-xs font-medium text-muted-foreground"
                            >
                                Confirm Password
                            </Label>
                            <Input
                                id="confirmPassword"
                                name="confirmPassword"
                                type="password"
                                required
                                placeholder="Repeat your password"
                                className={THESIS_INPUT_CLASS}
                            />
                        </div>

                        <TurnstileWidget
                            key={captchaKey}
                            onSuccess={(token) => setCaptchaToken(token)}
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
                                    className={LEADING_SPINNER_CLASS}
                                />
                            )}
                            Create account
                        </Button>
                    </Form>
                </div>
            </AuthShellPage>
        </AuthLayout>
    );
}
