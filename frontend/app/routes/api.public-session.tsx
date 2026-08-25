// Uncached micro-endpoint backing usePublicSession: returns the visitor's
// {isAuthenticated, userID, csrfToken} and sets/refreshes the csrf cookie.
// Exists so marketing documents can stay cookie-free + edge-cached (see
// lib/marketingCache.ts) while auth-aware UI and forms resolve per-visitor
// state client-side. Also persists rotated Supabase session cookies, keeping
// the refresh-persistence guarantee public loaders used to provide.
import type { LoaderFunctionArgs } from 'react-router';
import { json } from '~/lib/routerResponse';
import { createServerSupabaseClient } from '~/lib/supabase';
import { generateCsrfToken } from '~/lib/csrf.server';

export async function loader({ request }: LoaderFunctionArgs) {
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);
    const {
        data: { user },
    } = await supabase.auth.getUser();
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);
    headers.set('Cache-Control', 'no-store');

    return json(
        { isAuthenticated: !!user, userID: user?.id ?? null, csrfToken },
        { headers },
    );
}
