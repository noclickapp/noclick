// AuthModal component handles user authentication (login/signup) in a popup modal
// It communicates with the backend auth endpoints and manages the auth form state

import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Label } from '~/components/ui/label';
import { useFetcher } from 'react-router';
import { Building2, KeyRound, Mail, X } from 'lucide-react';
import { TurnstileWidget } from '~/components/auth/TurnstileWidget';
import {
    ButtonSpinner,
    GoogleIcon,
    LEADING_SPINNER_CLASS,
} from '~/components/auth/authFormShared';
import {
    AuthShellBrand,
    AUTH_GOOGLE_BUTTON_CLASS,
    THESIS_INPUT_CLASS,
    THESIS_PRIMARY_BUTTON_CLASS,
} from '~/components/auth/AuthShell';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import { resolveCsrfToken } from '~/lib/csrf';

interface AuthModalProps {
    isOpen: boolean;
    onClose: () => void;
    initialMode?: 'signin' | 'signup';
    /** URL to redirect to after successful authentication (full page navigation) */
    redirectTo?: string;
    /** Callback fired after successful authentication (before any redirect) */
    onAuthSuccess?: () => void;
    /** CSRF token for form submissions */
    csrfToken?: string;
}

export function AuthModal({
    isOpen,
    onClose,
    initialMode = 'signup',
    redirectTo,
    onAuthSuccess,
    csrfToken,
}: AuthModalProps) {
    const [authMode, setAuthMode] = useState<'signin' | 'signup'>(initialMode);
    const [showEmailAuth, setShowEmailAuth] = useState(false);
    const [showForgotPassword, setShowForgotPassword] = useState(false);
    const [showSSO, setShowSSO] = useState(false);
    const [ssoSlug, setSsoSlug] = useState('');
    const [captchaToken, setCaptchaToken] = useState<string>('');
    const [captchaKey, setCaptchaKey] = useState(0);
    const [hasSubmitted, setHasSubmitted] = useState(false);
    // Latched while an auth action that navigates the browser away is in flight.
    // The fetchers return JSON and go idle BEFORE the client-side redirect fires
    // (Google: window.location = authUrl; sign-in: reload / native form nav), so a
    // fetcher-state-only spinner flashes off in that gap. This holds it on through
    // the navigation; it's released only if the attempt comes back with an error.
    // One latch per button — a shared one spun BOTH buttons on either click.
    const [googleRedirecting, setGoogleRedirecting] = useState(false);
    const [formRedirecting, setFormRedirecting] = useState(false);
    const loginFetcher = useFetcher();
    const registerFetcher = useFetcher();
    const googleAuthFetcher = useFetcher();
    const forgotPasswordFetcher = useFetcher();
    const ssoFetcher = useFetcher();
    const { logActivity } = useAnalytics();
    const signupCapturedRef = useRef(false);

    // Sync authMode with initialMode when modal opens
    useEffect(() => {
        if (isOpen) {
            setAuthMode(initialMode);
            setShowEmailAuth(false);
            setShowForgotPassword(false);
            setShowSSO(false);
            setSsoSlug('');
            setCaptchaToken('');
            setHasSubmitted(false);
            setGoogleRedirecting(false);
            setFormRedirecting(false);
        }
    }, [isOpen, initialMode]);

    // Fire once each time the auth popup opens, so we can measure how many
    // visitors actually reach the login/signup popup — the top-of-funnel step
    // before user_signed_up. Keyed on isOpen only: fires on the open transition.
    useEffect(() => {
        if (!isOpen) return;
        logActivity(EVENTS.AUTH_MODAL_SHOWN, { mode: initialMode });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    // Select the appropriate fetcher based on mode
    const activeFetcher =
        authMode === 'signin' ? loginFetcher : registerFetcher;

    // Pending = fetcher in flight OR a navigation is underway (redirect latch).
    const googlePending =
        googleAuthFetcher.state !== 'idle' || googleRedirecting;
    const submitPending = activeFetcher.state !== 'idle' || formRedirecting;
    // Every auth surface locks while any one of them is in flight, but only the
    // one actually working shows the spinner.
    const anyAuthPending = googlePending || submitPending;

    // Sign-in posts to /auth/login, whose action hands back a refreshed token on
    // a stale-session error. Prefer it so the next submit self-heals without a
    // reload. (Sign-up posts to /auth/register, which doesn't validate CSRF, so
    // this just falls through to the loader-provided prop there.)
    const resolvedCsrfToken = resolveCsrfToken(csrfToken, activeFetcher.data);

    // For signin with redirectTo, the form submits naturally and the server handles redirect.
    // This effect only handles signup success (shows verification message) or signin without redirectTo.
    useEffect(() => {
        if (!hasSubmitted) return;

        // For signin with redirectTo, form submits naturally - no client handling needed
        if (authMode === 'signin' && redirectTo) return;

        const currentFetcher =
            authMode === 'signin' ? loginFetcher : registerFetcher;
        const data = currentFetcher.data as
            | { error?: string; success?: string }
            | undefined;
        const isIdle = currentFetcher.state === 'idle';
        const hasError = data?.error;
        const hasSuccessMessage = data?.success;

        // Don't proceed if not idle, no data, has error, or has success message (registration)
        if (!isIdle || !data || hasError || hasSuccessMessage) return;

        // Success: login completed without redirectTo
        setHasSubmitted(false);

        if (onAuthSuccess) {
            onAuthSuccess();
        }

        // Reload to refresh auth state
        window.location.reload();
    }, [
        loginFetcher.state,
        loginFetcher.data,
        registerFetcher.state,
        registerFetcher.data,
        authMode,
        hasSubmitted,
        onAuthSuccess,
        redirectTo,
    ]);

    // Fire analytics once per successful signup submission (email verification message means success).
    // Also stamps a localStorage marker so dashboard.tsx doesn't double-fire when the user lands
    // after clicking the verification link (user.created_at will still be recent).
    useEffect(() => {
        const data = registerFetcher.data as
            | { success?: string; error?: string }
            | undefined;
        if (
            registerFetcher.state === 'idle' &&
            data?.success &&
            !signupCapturedRef.current &&
            hasSubmitted
        ) {
            signupCapturedRef.current = true;
            try {
                localStorage.setItem('pc:signed_up_fired:email', '1');
            } catch {
                // Analytics still completes when browser storage is unavailable.
            }
            logActivity(EVENTS.USER_SIGNED_UP, { auth_method: 'email' });
        }
    }, [
        registerFetcher.state,
        registerFetcher.data,
        logActivity,
        hasSubmitted,
    ]);

    // Reset signup-capture guard when the modal re-opens so a second signup in the same session still fires
    useEffect(() => {
        if (isOpen) signupCapturedRef.current = false;
    }, [isOpen]);

    // Reset captcha after a real auth attempt so its single-use token isn't
    // replayed. A stale-session (CSRF) error carries a refreshed csrfToken and
    // never reached captcha verification, so keep the token there — otherwise the
    // submit button would be stuck disabled and the user couldn't retry.
    useEffect(() => {
        const activeFetcher =
            authMode === 'signin' ? loginFetcher : registerFetcher;
        if (
            activeFetcher.state === 'idle' &&
            activeFetcher.data &&
            !('csrfToken' in activeFetcher.data)
        ) {
            setCaptchaToken('');
            setCaptchaKey((prev) => prev + 1); // Force captcha widget remount
        }
    }, [
        loginFetcher.state,
        loginFetcher.data,
        registerFetcher.state,
        registerFetcher.data,
        authMode,
    ]);

    useEffect(() => {
        const data = googleAuthFetcher.data as { authUrl?: string } | undefined;
        if (googleAuthFetcher.state === 'idle' && data?.authUrl) {
            window.location.href = data.authUrl;
        }
    }, [googleAuthFetcher.state, googleAuthFetcher.data]);

    // Release the redirect latch if an auth attempt returns an error (no navigation
    // will happen), so the button doesn't spin forever. Success paths navigate away
    // and never need to reset.
    useEffect(() => {
        const gErr =
            googleAuthFetcher.state === 'idle' &&
            (googleAuthFetcher.data as { error?: string } | undefined)?.error;
        const lErr =
            loginFetcher.state === 'idle' &&
            (loginFetcher.data as { error?: string } | undefined)?.error;
        if (gErr) setGoogleRedirecting(false);
        if (lErr) setFormRedirecting(false);
    }, [
        googleAuthFetcher.state,
        googleAuthFetcher.data,
        loginFetcher.state,
        loginFetcher.data,
    ]);

    // Handle escape key
    useEffect(() => {
        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && isOpen) {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen, onClose]);

    // For SSR safety, check if we're in browser
    const [mounted, setMounted] = useState(false);
    useEffect(() => {
        setMounted(true);
    }, []);

    if (!isOpen || !mounted) return null;

    const handleGoogleAuth = () => {
        setGoogleRedirecting(true);
        googleAuthFetcher.submit(
            { provider: 'google', next: redirectTo || '' },
            { method: 'post', action: '/api/auth/google' }
        );
    };

    const handleSSOSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!ssoSlug.trim()) return;
        ssoFetcher.submit(
            { slug: ssoSlug.trim().toLowerCase() },
            { method: 'post', action: '/auth/sso' }
        );
    };

    const ssoError = (ssoFetcher.data as { error?: string } | undefined)?.error;

    const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
        // For signin with redirectTo, let form submit naturally so server redirect works
        if (authMode === 'signin' && redirectTo) {
            // Native form nav (no fetcher) — latch so the button stays in loading
            // state until the page navigates. Don't preventDefault.
            setFormRedirecting(true);
            return;
        }

        event.preventDefault();
        const formData = new FormData(event.currentTarget);
        setHasSubmitted(true);

        // For signup or signin without redirectTo, use fetcher
        const nextParam = redirectTo
            ? `?next=${encodeURIComponent(redirectTo)}`
            : '';
        const action =
            authMode === 'signin'
                ? `/auth/login${nextParam}`
                : `/auth/register${nextParam}`;

        if (authMode === 'signin') {
            // Sign-in ends in a reload/redirect — latch through the navigation.
            // (Sign-up ends in a verification message, so it stays fetcher-driven.)
            setFormRedirecting(true);
            loginFetcher.submit(formData, { method: 'post', action });
        } else {
            registerFetcher.submit(formData, { method: 'post', action });
        }
    };

    if (!isOpen) return null;

    return createPortal(
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/90 p-4 backdrop-blur-sm"
            onClick={onClose}
        >
            <motion.div
                data-testid="auth-shell-modal"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                className="relative mx-2 max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto rounded-3xl border border-border bg-sunken p-6 shadow-2xl sm:p-7"
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    type="button"
                    onClick={onClose}
                    aria-label="Close authentication"
                    className="absolute right-4 top-4 z-20 flex h-8 w-8 items-center justify-center rounded-full border border-border bg-background text-muted-foreground transition-colors hover:text-foreground"
                >
                    <X className="h-3.5 w-3.5" />
                </button>
                <AuthShellBrand compact />
                <AnimatePresence mode="wait">
                    {!showSSO ? (
                        <motion.div
                            key="main-auth"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0, x: -20 }}
                            transition={{ duration: 0.2 }}
                        >
                            <h3 className="mt-7 font-brand text-3xl font-medium leading-tight tracking-tight text-foreground">
                                {showForgotPassword
                                    ? 'Find your way back.'
                                    : authMode === 'signup'
                                      ? 'Your agent is waiting.'
                                      : 'Welcome back.'}
                            </h3>
                            <p className="mt-2 text-sm leading-6 text-muted-foreground">
                                {showForgotPassword
                                    ? "Enter your email and we'll send you a reset link."
                                    : authMode === 'signup'
                                      ? 'Build an agent, connect its tools, then let it run.'
                                      : 'Return to your workspace and pick up where you left off.'}
                            </p>

                            <div className="mt-6">
                                {!showEmailAuth && !showForgotPassword ? (
                                    <div
                                        data-testid="auth-modal-options"
                                        className="space-y-3"
                                    >
                                        <Button
                                            onClick={handleGoogleAuth}
                                            disabled={anyAuthPending}
                                            className={
                                                AUTH_GOOGLE_BUTTON_CLASS
                                            }
                                        >
                                            <span className="flex w-5 items-center justify-center">
                                                {googlePending ? (
                                                    <ButtonSpinner className="!h-5 !w-5" />
                                                ) : (
                                                    <GoogleIcon />
                                                )}
                                            </span>
                                            Continue with Google
                                        </Button>
                                        <Button
                                            type="button"
                                            onClick={() =>
                                                setShowEmailAuth(true)
                                            }
                                            className={
                                                AUTH_GOOGLE_BUTTON_CLASS
                                            }
                                        >
                                            <span className="flex w-5 items-center justify-center">
                                                <Mail className="h-5 w-5" />
                                            </span>
                                            Continue with email
                                        </Button>
                                        <Button
                                            type="button"
                                            onClick={() => setShowSSO(true)}
                                            className={
                                                AUTH_GOOGLE_BUTTON_CLASS
                                            }
                                        >
                                            <span className="flex w-5 items-center justify-center">
                                                <KeyRound className="h-5 w-5" />
                                            </span>
                                            Enterprise SSO
                                        </Button>
                                    </div>
                                ) : null}

                                {/* Error display */}
                                {showEmailAuth &&
                                    (() => {
                                        const data = activeFetcher.data as
                                            | { error?: string }
                                            | undefined;
                                        if (data?.error) {
                                            return (
                                                <div className="mb-4 p-3 text-red-600 dark:text-red-400 bg-red-400/10 rounded-lg text-sm">
                                                    {data.error}
                                                </div>
                                            );
                                        }
                                        return null;
                                    })()}

                                {/* Success message for registration */}
                                {showEmailAuth &&
                                    (() => {
                                        const data = registerFetcher.data as
                                            | { success?: string }
                                            | undefined;
                                        if (data?.success) {
                                            return (
                                                <div className="mb-4 p-3 text-green-600 dark:text-green-400 bg-green-400/10 rounded-lg text-sm">
                                                    {data.success}
                                                </div>
                                            );
                                        }
                                        return null;
                                    })()}

                                {showEmailAuth && !showForgotPassword && (
                                    <form
                                        data-testid="auth-modal-email-form"
                                        onSubmit={handleSubmit}
                                        method="post"
                                        action={
                                            authMode === 'signin' && redirectTo
                                                ? `/auth/login?next=${encodeURIComponent(redirectTo)}`
                                                : undefined
                                        }
                                        className="space-y-4"
                                    >
                                        {resolvedCsrfToken && (
                                            <input
                                                type="hidden"
                                                name="csrf_token"
                                                value={resolvedCsrfToken}
                                            />
                                        )}
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
                                                type={
                                                    authMode === 'signup'
                                                        ? 'email'
                                                        : 'text'
                                                }
                                                placeholder={
                                                    authMode === 'signup'
                                                        ? 'you@company.com'
                                                        : 'Email or username'
                                                }
                                                required
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
                                                {authMode === 'signin' ? (
                                                    <button
                                                        type="button"
                                                        onClick={() =>
                                                            setShowForgotPassword(
                                                                true
                                                            )
                                                        }
                                                        className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                                                    >
                                                        Forgot password?
                                                    </button>
                                                ) : null}
                                            </div>
                                            <Input
                                                id="password"
                                                name="password"
                                                type="password"
                                                placeholder={
                                                    authMode === 'signup'
                                                        ? 'At least 8 characters'
                                                        : 'Your password'
                                                }
                                                required
                                                className={THESIS_INPUT_CLASS}
                                            />
                                        </div>
                                        {authMode === 'signup' && (
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
                                                    placeholder="Repeat your password"
                                                    required
                                                    className={
                                                        THESIS_INPUT_CLASS
                                                    }
                                                />
                                            </div>
                                        )}

                                        <TurnstileWidget
                                            key={captchaKey} // Force remount after submission or mode switch
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
                                            disabled={
                                                anyAuthPending || !captchaToken
                                            }
                                            className={
                                                THESIS_PRIMARY_BUTTON_CLASS
                                            }
                                        >
                                            {submitPending && (
                                                <ButtonSpinner
                                                    className={
                                                        LEADING_SPINNER_CLASS
                                                    }
                                                />
                                            )}
                                            {authMode === 'signup'
                                                ? 'Create account'
                                                : 'Sign in'}
                                        </Button>
                                    </form>
                                )}

                                {showEmailAuth && !showForgotPassword && (
                                    <button
                                        type="button"
                                        onClick={() => setShowEmailAuth(false)}
                                        className="mt-4 text-sm text-muted-foreground transition-colors hover:text-foreground"
                                    >
                                        ← Back to options
                                    </button>
                                )}

                                {authMode === 'signin' &&
                                    !showForgotPassword && (
                                        <div
                                            data-testid="auth-modal-footer"
                                            className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-foreground/70"
                                        >
                                            <span>New to NoClick?</span>
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    setAuthMode('signup')
                                                }
                                                className="font-semibold text-foreground transition-opacity hover:opacity-75"
                                            >
                                                Create account
                                            </button>
                                        </div>
                                    )}

                                {authMode === 'signup' &&
                                    !showForgotPassword && (
                                        <div
                                            data-testid="auth-modal-footer"
                                            className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-foreground/70"
                                        >
                                            <span>
                                                Already have an account?
                                            </span>
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    setAuthMode('signin')
                                                }
                                                className="font-semibold text-foreground transition-opacity hover:opacity-75"
                                            >
                                                Sign in
                                            </button>
                                        </div>
                                    )}

                                {/* Forgot Password Form */}
                                {showForgotPassword && (
                                    <>
                                        <form
                                            onSubmit={(e) => {
                                                e.preventDefault();
                                                const formData = new FormData(
                                                    e.currentTarget
                                                );
                                                forgotPasswordFetcher.submit(
                                                    formData,
                                                    {
                                                        method: 'post',
                                                        action: '/api/auth/forgot-password',
                                                    }
                                                );
                                            }}
                                            className="space-y-4"
                                        >
                                            {(() => {
                                                const data =
                                                    forgotPasswordFetcher.data as
                                                        | { error?: string }
                                                        | undefined;
                                                if (data?.error) {
                                                    return (
                                                        <div className="p-3 text-red-600 dark:text-red-400 bg-red-400/10 rounded-lg text-sm">
                                                            {data.error}
                                                        </div>
                                                    );
                                                }
                                                return null;
                                            })()}

                                            {(() => {
                                                const data =
                                                    forgotPasswordFetcher.data as
                                                        | { success?: string }
                                                        | undefined;
                                                if (data?.success) {
                                                    return (
                                                        <div className="p-3 text-green-600 dark:text-green-400 bg-green-400/10 rounded-lg text-sm">
                                                            {data.success}
                                                        </div>
                                                    );
                                                }
                                                return null;
                                            })()}

                                            <Input
                                                name="email"
                                                type="email"
                                                placeholder="you@company.com"
                                                required
                                                aria-label="Email"
                                                className={THESIS_INPUT_CLASS}
                                            />

                                            <div className="flex gap-3">
                                                <Button
                                                    type="button"
                                                    onClick={() =>
                                                        setShowForgotPassword(
                                                            false
                                                        )
                                                    }
                                                    className="h-10 flex-1 rounded-xl border border-border bg-card text-sm text-foreground transition-colors hover:bg-accent"
                                                >
                                                    Back
                                                </Button>
                                                <Button
                                                    type="submit"
                                                    disabled={
                                                        forgotPasswordFetcher.state !==
                                                        'idle'
                                                    }
                                                    className="h-10 flex-1 rounded-xl bg-primary text-sm text-primary-foreground transition-colors hover:bg-primary/90"
                                                >
                                                    {forgotPasswordFetcher.state !==
                                                    'idle'
                                                        ? 'Sending...'
                                                        : 'Send Reset Link'}
                                                </Button>
                                            </div>
                                        </form>
                                    </>
                                )}
                            </div>
                        </motion.div>
                    ) : (
                        <motion.div
                            key="sso-auth"
                            initial={{ opacity: 0, x: 20 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: 20 }}
                            transition={{ duration: 0.2 }}
                        >
                            <div className="mb-6 mt-8 flex items-center gap-3">
                                <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center">
                                    <Building2 className="w-6 h-6 text-muted-foreground" />
                                </div>
                                <div className="text-left">
                                    <h3 className="font-brand text-lg font-semibold text-foreground">
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
                                        htmlFor="modal-sso-slug"
                                        className="mb-2 block text-left text-xs font-medium text-muted-foreground"
                                    >
                                        Organization
                                    </Label>
                                    <Input
                                        id="modal-sso-slug"
                                        type="text"
                                        required
                                        value={ssoSlug}
                                        onChange={(e) =>
                                            setSsoSlug(
                                                e.target.value
                                                    .toLowerCase()
                                                    .replace(/[^a-z0-9-]/g, '')
                                            )
                                        }
                                        placeholder="acme-corp"
                                        className={THESIS_INPUT_CLASS}
                                    />
                                    <p className="mt-2 text-sm text-muted-foreground/70 dark:text-zinc-500 text-left">
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
                                            className={LEADING_SPINNER_CLASS}
                                        />
                                    )}
                                    Continue with SSO
                                </Button>
                            </form>

                            <div className="mt-6 text-center">
                                <button
                                    type="button"
                                    onClick={() => {
                                        setShowSSO(false);
                                        setSsoSlug('');
                                    }}
                                    className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                                >
                                    ← Back to options
                                </button>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </motion.div>
        </motion.div>,
        document.body
    );
}
