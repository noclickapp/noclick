// Signing in: the owner's password (APP_PASSWORD), checked on the server (src/server/signIn.server.ts), for a session
// cookie.
import { useEffect, useState } from 'react';
import { Form, useActionData, useNavigation, useSearchParams } from 'react-router';
import { sendSignedInOn, signIn } from '@/server/signIn.server';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { PAGE_TITLE } from '@/ui/titles';
import type { Route } from './+types/login';

export const meta: Route.MetaFunction = () => [{ title: 'Sign in' }];

export const loader = (args: Route.LoaderArgs) => sendSignedInOn(args);
export const action = (args: Route.ActionArgs) => signIn(args);

export default function Login() {
    const result = useActionData<typeof action>();
    const [params] = useSearchParams();
    const submitting = useNavigation().state === 'submitting';
    // Off https (and away from localhost) the browser drops the Secure session cookie, so signing in would loop.
    const [insecure, setInsecure] = useState(false);
    useEffect(() => setInsecure(!window.isSecureContext), []);

    return (
        <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-8 px-6 py-16">
            <div className="flex flex-col gap-2">
                <h1 className={PAGE_TITLE}>Sign in</h1>
                <p className="text-[14px] text-muted-foreground">This app is private. Enter the password its owner set for it.</p>
            </div>
            {insecure && (
                <p role="alert" className="text-[14px] text-amber-600 dark:text-amber-400">
                    This page isn’t served over https, so your browser won’t keep the sign-in. Serve the app over https.
                </p>
            )}
            <Form method="post" replace className="flex flex-col gap-5">
                <input type="hidden" name="next" value={params.get('next') ?? '/'} />
                <div>
                    <label htmlFor="password" className={FIELD_LABEL}>
                        Password
                    </label>
                    <input id="password" type="password" name="password" autoComplete="current-password" required autoFocus className={FIELD} />
                </div>
                {result?.error && (
                    <p role="alert" className="text-[14px] text-red-600 dark:text-red-400">
                        {result.error}
                    </p>
                )}
                <button type="submit" disabled={submitting} className={`${BUTTON_PRIMARY} justify-center`}>
                    {submitting ? 'Signing in…' : 'Sign in'}
                </button>
            </Form>
        </main>
    );
}
