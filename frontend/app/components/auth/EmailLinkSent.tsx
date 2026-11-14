// The "check your email" line of sign-up and password reset. A link tapped in Mail opens the browser, never
// an app added to the home screen, and that app keeps its own sign-in, so inside the app the line says to come
// back and sign in once the link is done.
import { useInstalledApp } from '~/hooks/useInstalledApp';

export function EmailLinkSent({ message, inApp }: { message: string; inApp: string }) {
    const installed = useInstalledApp();
    return (
        <div className="mb-6 rounded-2xl bg-green-500/10 p-4 text-sm text-green-600 dark:text-green-400">
            {message}
            {installed && <p className="mt-2">{inApp}</p>}
        </div>
    );
}
