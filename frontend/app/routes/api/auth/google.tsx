// API route for initiating Google OAuth login
// Returns the OAuth URL for client-side redirect
// Supports 'next' parameter for post-auth redirect (e.g., from public workflow fork flow)

import { type ActionFunctionArgs } from 'react-router';
import { json } from '~/lib/routerResponse';
import { authenticate } from '~/lib/auth.server';

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const nextUrl = formData.get('next') as string | null;

    const { error, authUrl, headers } = await authenticate(request, 'google', undefined, nextUrl || undefined);

    if (error || !authUrl) {
        return json({ error: error || 'Failed to initialize Google login' }, { status: 400, headers });
    }

    return json({ authUrl }, { headers });
}