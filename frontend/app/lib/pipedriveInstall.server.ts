// Authenticate installation on a clean destination, never on a URL carrying
// a provider code. Forward rotated auth cookies and prevent caching/referrer
// leaks for successful authentication and login redirects alike.

import { requireAuth } from '~/lib/supabase';
import {
    PIPEDRIVE_INSTALL_PATH,
    PIPEDRIVE_INSTALL_HEADERS,
} from './pipedriveInstall';

export async function requirePipedriveInstallAuth(request: Request) {
    const cleanRequest = new Request(
        new URL(PIPEDRIVE_INSTALL_PATH, request.url),
        {
            headers: request.headers,
        }
    );
    const protect = (headers: Headers) => {
        for (const [name, value] of Object.entries(PIPEDRIVE_INSTALL_HEADERS))
            headers.set(name, value);
    };
    try {
        const auth = await requireAuth(cleanRequest);
        protect(auth.headers);
        return auth;
    } catch (response) {
        if (response instanceof Response) protect(response.headers);
        throw response;
    }
}
