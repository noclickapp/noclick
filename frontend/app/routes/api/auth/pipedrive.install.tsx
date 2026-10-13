// Marketplace installations arrive in a tab, not an editor popup.
// Sign in on a clean URL before requesting a new browser-bound authorization;
// never carry the Marketplace's unbound code through login or registration.

import { redirect, type LoaderFunctionArgs } from 'react-router';
import { requirePipedriveInstallAuth } from '~/lib/pipedriveInstall.server';

export async function loader({ request }: LoaderFunctionArgs) {
    const { headers } = await requirePipedriveInstallAuth(request);
    return redirect('/api/auth/pipedrive/authorize?mode=install', { headers });
}
