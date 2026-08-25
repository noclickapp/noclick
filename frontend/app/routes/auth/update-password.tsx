import { type ActionFunctionArgs, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Update Password - NoClick',
        description: 'Update your NoClick account password.',
        indexable: false,
    });
import { useActionData, Form, Link } from 'react-router';
import { requireAuth, createServerSupabaseClient } from '~/lib/supabase';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Label } from '~/components/ui/label';
import { motion } from 'framer-motion';
import { AuthLayout } from '~/components/auth/AuthLayout';

export async function loader({ request }: LoaderFunctionArgs) {
    const { headers } = await requireAuth(request);
    return json({}, { headers });
}

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const password = formData.get('password') as string;
    const confirmPassword = formData.get('confirmPassword') as string;

    if (password !== confirmPassword) {
        return json(
            {
                error: 'Passwords do not match.',
            },
            { status: 400 }
        );
    }

    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);

    const { error } = await supabase.auth.updateUser({
        password: password,
    });

    if (error) {
        console.error('Password update error:', error);
        return json(
            {
                error: `Failed to update password: ${error.message}`,
            },
            { status: 400, headers }
        );
    }

    return json(
        {
            success:
                'Password updated successfully. You can now login with your new password.',
        },
        { headers }
    );
}

export default function UpdatePassword() {
    const actionData = useActionData() as JsonPayloadOf<typeof action>;

    return (
        <AuthLayout
            quote={{
                text: "The secret of change is to focus all of your energy not on fighting the old, but on building the new.",
                author: "Socrates"
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
                            Update Password
                        </h1>
                        <p className="text-muted-foreground dark:text-white/70 text-lg">
                            Enter your new password below
                        </p>
                    </motion.div>
                </div>

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className="bg-sunken border border-border rounded-2xl p-8"
                >
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
                        <div>
                            <Label
                                htmlFor="password"
                                className="block text-sm font-medium text-muted-foreground dark:text-zinc-300 mb-2"
                            >
                                New Password
                            </Label>
                            <Input
                                id="password"
                                name="password"
                                type="password"
                                required
                                placeholder="••••••••••••"
                                className="w-full bg-card/90 border border-border dark:border-zinc-700/60 text-foreground placeholder:text-[hsl(var(--placeholder))] h-11 focus:border-foreground/40 focus:ring-0 transition-all rounded-lg backdrop-blur-sm"
                            />
                        </div>

                        <div>
                            <Label
                                htmlFor="confirmPassword"
                                className="block text-sm font-medium text-muted-foreground dark:text-zinc-300 mb-2"
                            >
                                Confirm Password
                            </Label>
                            <Input
                                id="confirmPassword"
                                name="confirmPassword"
                                type="password"
                                required
                                placeholder="••••••••••••"
                                className="w-full bg-card/90 border border-border dark:border-zinc-700/60 text-foreground placeholder:text-[hsl(var(--placeholder))] h-11 focus:border-foreground/40 focus:ring-0 transition-all rounded-lg backdrop-blur-sm"
                            />
                        </div>

                        <Button
                            type="submit"
                            className="w-full bg-primary hover:bg-primary/90 text-primary-foreground h-12 font-medium transition-all shadow-sm"
                        >
                            Update Password
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
