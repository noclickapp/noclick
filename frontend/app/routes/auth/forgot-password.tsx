import { type ActionFunctionArgs, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Forgot Password - NoClick',
        description: 'Reset your NoClick account password.',
        indexable: false,
    });
import { useActionData, useLoaderData, Form, Link } from 'react-router';
import { requireGuest } from '~/lib/supabase';
import { authenticate } from '~/lib/auth.server';
import { generateCsrfToken, csrfFailureResponse } from '~/lib/csrf.server';
import { resolveCsrfToken } from '~/lib/csrf';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Label } from '~/components/ui/label';
import { motion } from 'framer-motion';
import { AuthLayout } from '~/components/auth/AuthLayout';
import { AuthPageHeader } from '~/components/auth/AuthPageHeader';
import { AUTH_INPUT_CLASS, AUTH_LABEL_CLASS, AUTH_LINK_CLASS, AUTH_PRIMARY_BUTTON_CLASS } from '~/components/auth/authStyle';

export async function loader({ request }: LoaderFunctionArgs) {
    // Forward requireGuest's headers so a refreshed session is persisted, then
    // add the CSRF cookie alongside it (append, don't overwrite).
    const { headers, env } = await requireGuest(request);
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);
    return json({ csrfToken, env }, { headers });
}

export async function action({ request }: ActionFunctionArgs) {
    // Self-healing CSRF check: hands back a fresh token+cookie on a stale-session
    // failure so the next submit works without a page reload.
    const csrfFailure = await csrfFailureResponse(request);
    if (csrfFailure) return csrfFailure;
    const formData = await request.formData();
    const email = formData.get('email') as string;

    const { error, success, headers } = await authenticate(request, 'reset', { email });

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    return json({ success }, { status: 200, headers });
}

export default function ForgotPassword() {
    const { csrfToken } = useLoaderData() as JsonPayloadOf<typeof loader>;
    const actionData = useActionData() as JsonPayloadOf<typeof action>;
    // Prefer the token a stale-session error hands back so retry self-heals.
    const freshCsrfToken = resolveCsrfToken(csrfToken, actionData);

    return (
        <AuthLayout>
            <div>
                <AuthPageHeader back={{ to: '/auth/login', label: 'Back to login' }} title="Reset Password" description="Enter your email to receive reset instructions" />

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className="">

                    {actionData && 'error' in actionData && (
                        <div className="mb-6 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-2xl text-sm">
                            {actionData.error}
                        </div>
                    )}

                    {actionData && 'success' in actionData && (
                        <div className="mb-6 p-4 text-green-600 dark:text-green-400 bg-green-500/10 rounded-2xl text-sm">
                            {actionData.success}
                        </div>
                    )}

                    <Form method="post" className="space-y-5">
                        <input type="hidden" name="csrf_token" value={freshCsrfToken} />
                        <div>
                            <Label
                                htmlFor="email"
                                className={AUTH_LABEL_CLASS}
                            >
                                Email
                            </Label>
                            <Input
                                id="email"
                                name="email"
                                type="email"
                                required
                                placeholder="name@example.com"
                                className={AUTH_INPUT_CLASS}
                            />
                        </div>

                        <Button
                            type="submit"
                            className={AUTH_PRIMARY_BUTTON_CLASS}
                        >
                            Reset
                        </Button>
                    </Form>

                    <div className="mt-6 text-sm">
                        <span className="text-foreground/60 dark:text-foreground/55">
                            Remember your password?{' '}
                        </span>
                        <Link
                            to="/auth/login"
                            className={AUTH_LINK_CLASS}
                        >
                            Sign in
                        </Link>
                    </div>
                </motion.div>
            </div>
        </AuthLayout>
    );
}
