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
import { AuthPageHeader } from '~/components/auth/AuthPageHeader';
import { AUTH_INPUT_CLASS, AUTH_LABEL_CLASS, AUTH_LINK_CLASS, AUTH_PRIMARY_BUTTON_CLASS } from '~/components/auth/authStyle';

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
        <AuthLayout>
            <div>
                <AuthPageHeader back={{ to: '/auth/login', label: 'Back to login' }} title="Update Password" description="Enter your new password below" />

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className=""
                >
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
                        <div>
                            <Label
                                htmlFor="password"
                                className={AUTH_LABEL_CLASS}
                            >
                                New Password
                            </Label>
                            <Input
                                id="password"
                                name="password"
                                type="password"
                                required
                                placeholder="••••••••••••"
                                className={AUTH_INPUT_CLASS}
                            />
                        </div>

                        <div>
                            <Label
                                htmlFor="confirmPassword"
                                className={AUTH_LABEL_CLASS}
                            >
                                Confirm Password
                            </Label>
                            <Input
                                id="confirmPassword"
                                name="confirmPassword"
                                type="password"
                                required
                                placeholder="••••••••••••"
                                className={AUTH_INPUT_CLASS}
                            />
                        </div>

                        <Button
                            type="submit"
                            className={AUTH_PRIMARY_BUTTON_CLASS}
                        >
                            Update Password
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
