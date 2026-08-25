// Embedded auth panel for the invite landing (/i/<token>). The invite page is
// only shown to logged-out visitors, so it carries the real auth surface:
// Google sign-in, email/password sign-up & sign-in (toggle), and the Cloudflare
// Turnstile captcha. All of it posts to the /i/<token> route action, which runs
// `authenticate(...)` with next=/i/<token> so the user bounces back here after
// auth and the invite is redeemed.

import { useEffect, useState } from 'react';
import { Form, useActionData, useNavigation } from 'react-router';
import { TurnstileWidget } from '~/components/auth/TurnstileWidget';
import { resolveCsrfToken } from '~/lib/csrf';
import { isLocalEdition } from '~/lib/edition';

interface InviteAuthPanelProps {
    csrfToken: string;
    ownerName: string;
}

const inputCls =
    'h-12 w-full rounded-xl border border-border dark:border-zinc-700/60 bg-card/80 px-4 text-[15px] text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none transition-colors focus:border-ring';

export function InviteAuthPanel({ csrfToken, ownerName }: InviteAuthPanelProps) {
    const actionData = useActionData() as { error?: string; success?: string; csrfToken?: string } | undefined;
    const navigation = useNavigation();
    const freshCsrf = resolveCsrfToken(csrfToken, actionData);

    const [mode, setMode] = useState<'signup' | 'signin'>('signup');
    const [captchaToken, setCaptchaToken] = useState('');
    const [captchaKey, setCaptchaKey] = useState(0);

    // Reset captcha after a real attempt (a CSRF/stale-session error carries a
    // fresh csrfToken and never reached captcha, so keep the token in that case).
    useEffect(() => {
        if (actionData && !('csrfToken' in actionData)) {
            setCaptchaToken('');
            setCaptchaKey((k) => k + 1);
        }
    }, [actionData]);

    const submitting = navigation.state === 'submitting';
    const success = actionData?.success;

    // Registration success → "check your email".
    if (success) {
        return (
            <div className="w-full max-w-[440px]">
                <div className="rounded-3xl border border-foreground/10 bg-sunken/70 dark:bg-sunken/60 p-9 backdrop-blur-xl">
                    <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full border border-emerald-400/20 bg-emerald-400/10">
                        <svg viewBox="0 0 24 24" className="h-6 w-6 text-emerald-600 dark:text-emerald-300" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                            <path d="m4 8 8 5 8-5" />
                            <rect x="3" y="5" width="18" height="14" rx="2" />
                        </svg>
                    </div>
                    <h2 className="text-[22px] font-semibold tracking-tight text-foreground">Check your email</h2>
                    <p className="mt-2.5 text-[14.5px] leading-relaxed text-muted-foreground">{success}</p>
                    <p className="mt-3 text-[14px] text-muted-foreground/70 dark:text-zinc-500">
                        Confirm your address and you’ll land straight on {ownerName}’s workflow.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="w-full max-w-[440px]">
            <div className="rounded-3xl border border-foreground/10 bg-sunken/70 dark:bg-sunken/60 p-9 backdrop-blur-xl">
                <h2 className="text-[26px] font-semibold tracking-tight text-foreground">
                    {mode === 'signup' ? 'Create your account' : 'Welcome back'}
                </h2>
                <p className="mt-1.5 text-[15px] text-muted-foreground">
                    {mode === 'signup' ? `Join ${ownerName} on this workflow.` : 'Sign in to join this workflow.'}
                </p>

                {actionData?.error && (
                    <div className="mt-6 rounded-xl bg-red-500/10 px-4 py-3 text-[14px] text-red-600 dark:text-red-400">{actionData.error}</div>
                )}

                {/* Google — skips CSRF by design (OAuth state/PKCE protects it) */}
                {!isLocalEdition() && (
                    <>
                    <Form method="post" className="mt-6">
                        <input type="hidden" name="provider" value="google" />
                        <button
                            type="submit"
                            className="flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-border dark:border-zinc-700/60 bg-card/80 text-[15px] font-medium text-foreground transition-colors hover:border-foreground/20 hover:bg-accent"
                        >
                            <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden>
                                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                            </svg>
                            Continue with Google
                        </button>
                    </Form>

                    <div className="my-6 flex items-center gap-3">
                        <div className="h-px flex-1 bg-foreground/10" />
                        <span className="text-[11px] uppercase tracking-wide text-muted-foreground/60 dark:text-zinc-600">or</span>
                        <div className="h-px flex-1 bg-foreground/10" />
                    </div>
                    </>
                )}

                {/* Email + password */}
                <Form method="post" className="space-y-3.5">
                    <input type="hidden" name="csrf_token" value={freshCsrf} />
                    <input type="hidden" name="intent" value={mode === 'signup' ? 'register' : 'login'} />
                    <input name="email" type="email" required placeholder="name@example.com" autoComplete="email" className={inputCls} />
                    <input
                        name="password"
                        type="password"
                        required
                        placeholder="Password"
                        autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                        className={inputCls}
                    />
                    {mode === 'signup' && (
                        <input name="confirmPassword" type="password" required placeholder="Confirm password" autoComplete="new-password" className={inputCls} />
                    )}

                    <TurnstileWidget key={captchaKey} fullWidth onSuccess={(t) => setCaptchaToken(t)} onError={() => setCaptchaToken('')} />
                    <input type="hidden" name="captchaToken" value={captchaToken} />

                    <button
                        type="submit"
                        disabled={!captchaToken || submitting}
                        className="inline-flex h-12 w-full items-center justify-center rounded-xl bg-primary text-[15px] font-semibold text-primary-foreground transition-all hover:bg-primary/90 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {submitting ? 'Working…' : mode === 'signup' ? 'Create account & join' : 'Sign in & join'}
                    </button>
                </Form>

                <p className="mt-6 text-center text-[14px] text-muted-foreground/70 dark:text-zinc-500">
                    {mode === 'signup' ? 'Already have an account? ' : 'New to NoClick? '}
                    <button
                        type="button"
                        onClick={() => setMode(mode === 'signup' ? 'signin' : 'signup')}
                        className="font-medium text-foreground/90 underline-offset-2 transition-colors hover:text-foreground hover:underline"
                    >
                        {mode === 'signup' ? 'Sign in' : 'Create one'}
                    </button>
                </p>
            </div>
        </div>
    );
}
