/**
 * SSO login route for enterprise SAML authentication.
 * Users enter their company domain and are redirected to their identity provider.
 */

import { redirect, type ActionFunctionArgs, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'SSO Sign In - NoClick',
        description: 'Sign in to NoClick with your enterprise SSO provider.',
        indexable: false,
    });
import { useActionData, Form, Link, useSearchParams, useFetcher } from 'react-router';
import { requireGuest } from '~/lib/supabase';
import { authenticate } from '~/lib/auth.server';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Label } from '~/components/ui/label';
import { motion } from 'framer-motion';
import { AuthLayout } from '~/components/auth/AuthLayout';
import { useState, useEffect, useRef } from 'react';

export async function loader({ request }: LoaderFunctionArgs) {
    // Forward requireGuest's headers so a refreshed session is persisted.
    const { headers } = await requireGuest(request);

    // Check for org hint in URL (e.g., from org invite link or Okta SP-initiated)
    const url = new URL(request.url);
    const orgHint = url.searchParams.get('org');
    const error = url.searchParams.get('error');
    // Auto-submit flag for seamless SP-initiated SSO from IdP catalogs
    const autoSubmit = url.searchParams.get('auto') === 'true';

    return json({ orgHint, error, autoSubmit }, { headers });
}

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const slug = (formData.get('slug') as string)?.trim().toLowerCase();

    if (!slug) {
        return json({ error: 'Please enter your organization identifier' }, { status: 400 });
    }

    // Basic slug validation (alphanumeric and hyphens, 2+ chars)
    if (!/^[a-z0-9-]{2,}$/.test(slug)) {
        return json({ error: 'Please enter a valid organization identifier' }, { status: 400 });
    }

    // Get the 'next' parameter for post-login redirect
    const url = new URL(request.url);
    const nextUrl = url.searchParams.get('next');

    const { error, ssoUrl, headers } = await authenticate(request, 'sso', { slug }, nextUrl || undefined);

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    if (!ssoUrl) {
        return json({ error: 'Failed to initialize SSO login. Please try again.' }, { status: 400, headers });
    }

    // Redirect to identity provider
    return redirect(ssoUrl, { headers });
}

export default function SSOLogin() {
    const actionData = useActionData() as JsonPayloadOf<typeof action>;
    const [searchParams] = useSearchParams();
    const slugHint = searchParams.get('org') || '';
    const autoSubmit = searchParams.get('auto') === 'true';
    const [slug, setSlug] = useState(slugHint);
    const [isAutoSubmitting, setIsAutoSubmitting] = useState(false);
    const fetcher = useFetcher();
    const hasAutoSubmitted = useRef(false);

    // Preserve redirect URL for navigation between auth pages
    const nextUrl = searchParams.get('next');
    const nextParam = nextUrl ? `?next=${encodeURIComponent(nextUrl)}` : '';

    // Auto-submit for seamless SP-initiated SSO (e.g., from Okta app catalog)
    useEffect(() => {
        if (autoSubmit && slugHint && !hasAutoSubmitted.current) {
            hasAutoSubmitted.current = true;
            setIsAutoSubmitting(true);
            fetcher.submit(
                { slug: slugHint },
                { method: 'post', action: `/auth/sso${nextParam}` }
            );
        }
    }, [autoSubmit, slugHint, nextParam, fetcher]);

    // Show loading state during auto-submit
    if (isAutoSubmitting && fetcher.state !== 'idle') {
        return (
            <AuthLayout>
                <div className="flex min-h-[400px] items-center justify-center">
                    <div className="text-center">
                        <div className="animate-spin h-8 w-8 border-4 border-foreground border-t-transparent rounded-full mx-auto"></div>
                        <p className="mt-4 text-muted-foreground">Connecting to your identity provider...</p>
                    </div>
                </div>
            </AuthLayout>
        );
    }

    // Show error from auto-submit
    const displayError = actionData?.error || (fetcher.data as { error?: string } | undefined)?.error;

    return (
        <AuthLayout>
            <div>
                <div className="mb-10">
                    <Link to={`/auth/login${nextParam}`} className="inline-flex items-center text-sm text-muted-foreground dark:text-white/70 hover:text-foreground mb-8 transition-colors">
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
                            Enterprise SSO
                        </h1>
                        <p className="text-muted-foreground dark:text-white/70 text-lg">
                            Sign in with your company's identity provider
                        </p>
                    </motion.div>
                </div>

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className="bg-sunken border border-border rounded-2xl p-8"
                >
                    {displayError && (
                        <div className="mb-6 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg text-sm">
                            {displayError}
                        </div>
                    )}

                    <Form method="post" className="space-y-5">
                        <div>
                            <Label
                                htmlFor="slug"
                                className="block text-sm font-medium text-muted-foreground dark:text-zinc-300 mb-2"
                            >
                                Organization
                            </Label>
                            <Input
                                id="slug"
                                name="slug"
                                type="text"
                                required
                                autoFocus
                                autoComplete="organization"
                                value={slug}
                                onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
                                placeholder="acme-corp"
                                className="w-full bg-card/90 border border-border dark:border-zinc-700/60 text-foreground placeholder:text-[hsl(var(--placeholder))] h-11 focus:border-foreground/40 focus:ring-0 transition-all rounded-lg backdrop-blur-sm"
                            />
                            <p className="mt-2 text-sm text-muted-foreground/70 dark:text-zinc-500">
                                Enter your organization's NoClick workspace identifier
                            </p>
                        </div>

                        <Button
                            type="submit"
                            className="w-full bg-primary hover:bg-primary/90 text-primary-foreground h-12 font-medium transition-all shadow-sm"
                        >
                            Continue with SSO
                        </Button>
                    </Form>

                    <div className="mt-6 p-4 bg-muted/50 dark:bg-zinc-900/50 rounded-lg">
                        <p className="text-sm text-muted-foreground">
                            <span className="font-medium text-foreground">How it works:</span>{' '}
                            You'll be redirected to your company's identity provider to authenticate, then returned to NoClick.
                        </p>
                    </div>

                    <div className="mt-6 text-center text-sm">
                        <span className="text-muted-foreground">Don't have SSO? </span>
                        <Link
                            to={`/auth/login${nextParam}`}
                            className="font-medium text-foreground/90 hover:text-foreground transition-colors"
                        >
                            Sign in with email
                        </Link>
                    </div>
                </motion.div>
            </div>
        </AuthLayout>
    );
}
