/*
Catch-all error page for failed auth callbacks (/auth/callback, /auth/confirm,
/auth/reset-password). The `reason` search param carries the Supabase error code so the copy
matches the actual failure and analytics can distinguish causes.
*/
import { Button } from '~/components/ui/button';
import { Link, useSearchParams } from 'react-router';
import { motion } from 'framer-motion';
import { useEffect } from 'react';
import { AuthLayout } from '~/components/auth/AuthLayout';
import type { MetaFunction } from 'react-router';
import { buildSeoMeta } from '~/lib/seo';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

const DEFAULT_MESSAGE =
    'This could be because the link has expired or was already used. Please try requesting a new link.';

// PKCE exchange failures: the code verifier lives in the browser that started the flow.
const CROSS_BROWSER_MESSAGE =
    'We couldn’t complete your sign-in. This usually happens when a link is opened in a ' +
    'different browser or device than the one it was requested from. Please request a new link ' +
    'and open it in the same browser.';
const SERVER_FAULT_MESSAGE =
    'Something went wrong on our end while signing you in. Please try again in a moment — ' +
    'if it keeps happening, contact support.';

// Copy keyed by the Supabase error code forwarded as ?reason=; anything else gets DEFAULT_MESSAGE.
const REASON_MESSAGES: Record<string, string> = {
    otp_expired:
        'This link has expired or was already used. Email links are single-use, and some email ' +
        'providers pre-open links for security scanning, which can consume them. Please request a new link.',
    // GoTrue returns validation_failed ("code verifier should be non-empty") when the PKCE
    // exchange runs in a browser that never held the verifier cookie — the cross-context case.
    validation_failed: CROSS_BROWSER_MESSAGE,
    flow_state_not_found: CROSS_BROWSER_MESSAGE,
    flow_state_expired: CROSS_BROWSER_MESSAGE,
    bad_code_verifier: CROSS_BROWSER_MESSAGE,
    unexpected_failure: SERVER_FAULT_MESSAGE,
    server_error: SERVER_FAULT_MESSAGE,
};

// For these failures GoTrue has usually already confirmed the email by the time the
// redirect fails (verification happens before the code exchange), so signing in with
// the original credentials tends to just work. Surface that instead of a dead end.
const LIKELY_ALREADY_VERIFIED = new Set([
    'otp_expired',
    'validation_failed',
    'flow_state_not_found',
    'flow_state_expired',
    'bad_code_verifier',
]);

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Sign In Error - NoClick',
        description: 'Something went wrong while signing you in.',
        indexable: false,
    });

export default function AuthCodeError() {
    const [searchParams] = useSearchParams();
    const { logActivity } = useAnalytics();
    const reason = searchParams.get('reason');
    const message = (reason && REASON_MESSAGES[reason]) || DEFAULT_MESSAGE;

    useEffect(() => {
        // reason is URL-controlled; cap it so junk requests can't spray unbounded values
        logActivity(EVENTS.AUTH_ERROR_PAGE_SHOWN, {
            reason: (reason || 'unknown').slice(0, 64),
            surface: 'error_page',
        });
    }, [logActivity, reason]);

    return (
        <AuthLayout>
            <div>
                <div className="mb-10">
                    <Link to="/auth/login" className="inline-flex items-center text-sm text-muted-foreground dark:text-white/70 hover:text-foreground mb-8 transition-colors">
                        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                        </svg>
                        Back to login
                    </Link>

                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.5 }}
                    >
                        <h1 className="text-4xl font-bold text-foreground mb-3">
                            Authentication Error
                        </h1>
                        <p className="text-muted-foreground dark:text-white/70 text-lg">
                            There was an error verifying your authentication code
                        </p>
                    </motion.div>
                </div>

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className="bg-sunken border border-border rounded-2xl p-8"
                >
                    <p className="text-muted-foreground dark:text-zinc-300 mb-8 text-center">
                        {message}
                    </p>

                    {reason && LIKELY_ALREADY_VERIFIED.has(reason) && (
                        <p className="text-muted-foreground dark:text-zinc-300 mb-8 text-center text-sm">
                            If you were confirming a new account, your email is likely already
                            verified. Signing in with your email and password should work.
                        </p>
                    )}

                    <Button
                        asChild
                        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground h-12 font-medium transition-all shadow-sm"
                    >
                        <Link to="/auth/login">Return to Login</Link>
                    </Button>

                    <div className="mt-6 text-center text-sm">
                        <span className="text-muted-foreground">
                            Need help?{' '}
                        </span>
                        <Link
                            to="/auth/forgot-password"
                            className="font-medium text-foreground/90 hover:text-foreground transition-colors"
                        >
                            Reset password
                        </Link>
                    </div>
                </motion.div>
            </div>
        </AuthLayout>
    );
}
