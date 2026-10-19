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
import { AuthPageHeader } from '~/components/auth/AuthPageHeader';
import { AUTH_INPUT_CLASS, AUTH_LABEL_CLASS, AUTH_LINK_CLASS, AUTH_PRIMARY_BUTTON_CLASS } from '~/components/auth/authStyle';
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
                        <p className="mt-4 text-foreground/60">Connecting to your identity provider...</p>
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
                <AuthPageHeader back={{ to: `/auth/login${nextParam}`, label: 'Back to login' }} title="Enterprise SSO" description="Sign in with your company's identity provider" />

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className=""
                >
                    {displayError && (
                        <div className="mb-6 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-2xl text-sm">
                            {displayError}
                        </div>
                    )}

                    <Form method="post" className="space-y-5">
                        <div>
                            <Label
                                htmlFor="slug"
                                className={AUTH_LABEL_CLASS}
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
                                className={AUTH_INPUT_CLASS}
                            />
                            <p className="mt-2 text-[13px] text-foreground/60 dark:text-foreground/50">
                                Enter your organization's NoClick workspace identifier
                            </p>
                        </div>

                        <Button
                            type="submit"
                            className={AUTH_PRIMARY_BUTTON_CLASS}
                        >
                            Continue with SSO
                        </Button>
                    </Form>

                    <div className="mt-6 rounded-2xl bg-foreground/[0.04] p-4">
                        <p className="text-sm text-foreground/60">
                            <span className="font-medium text-foreground">How it works:</span>{' '}
                            You'll be redirected to your company's identity provider to authenticate, then returned to NoClick.
                        </p>
                    </div>

                    <div className="mt-6 text-sm">
                        <span className="text-foreground/60 dark:text-foreground/55">Don't have SSO? </span>
                        <Link
                            to={`/auth/login${nextParam}`}
                            className={AUTH_LINK_CLASS}
                        >
                            Sign in with email
                        </Link>
                    </div>
                </motion.div>
            </div>
        </AuthLayout>
    );
}
