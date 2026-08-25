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
        <AuthLayout 
            quote={{
                text: "Without forgetting it is quite impossible to live at all.",
                author: "Friedrich Nietzsche"
            }}
        >
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
                            Reset Password
                        </h1>
                        <p className="text-muted-foreground dark:text-white/70 text-lg">
                            Enter your email to receive reset instructions
                        </p>
                    </motion.div>
                </div>

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className="bg-sunken border border-border rounded-2xl p-8">

                    {actionData && 'error' in actionData && (
                        <div className="mb-6 p-4 text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg text-sm">
                            {actionData.error}
                        </div>
                    )}

                    {actionData && 'success' in actionData && (
                        <div className="mb-6 p-4 text-green-600 dark:text-green-400 bg-green-500/10 rounded-lg text-sm">
                            {actionData.success}
                        </div>
                    )}

                    <Form method="post" className="space-y-5">
                        <input type="hidden" name="csrf_token" value={freshCsrfToken} />
                        <div>
                            <Label
                                htmlFor="email"
                                className="block text-sm font-medium text-muted-foreground dark:text-zinc-300 mb-2"
                            >
                                Email
                            </Label>
                            <Input
                                id="email"
                                name="email"
                                type="email"
                                required
                                placeholder="name@example.com"
                                className="w-full bg-card/90 border border-border dark:border-zinc-700/60 text-foreground placeholder:text-[hsl(var(--placeholder))] h-11 focus:border-foreground/40 focus:ring-0 transition-all rounded-lg backdrop-blur-sm"
                            />
                        </div>

                        <Button
                            type="submit"
                            className="w-full bg-primary hover:bg-primary/90 text-primary-foreground h-12 font-medium transition-all shadow-sm"
                        >
                            Reset
                        </Button>
                    </Form>

                    <div className="mt-6 text-center text-sm">
                        <span className="text-muted-foreground">
                            Remember your password?{' '}
                        </span>
                        <Link
                            to="/auth/login"
                            className="font-medium text-foreground/90 hover:text-foreground transition-colors"
                        >
                            Sign in
                        </Link>
                    </div>
                </motion.div>
            </div>
        </AuthLayout>
    );
}
