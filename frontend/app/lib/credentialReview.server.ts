// Credential review pages use the signed-in browser session, not an agent token.
// This shared proxy preserves refreshed auth cookies and requires CSRF on every
// decision or policy edit before forwarding it to the owner-checked backend.
import { json } from '~/lib/routerResponse';
import { requireAuth } from '~/lib/supabase';
import { csrfFailureResponse, generateCsrfToken } from '~/lib/csrf.server';

async function backend(path: string, token: string, body?: unknown) {
    const response = await fetch(
        `${process.env.API_URL}/api/credential-request/${path}`,
        {
            method: body === undefined ? 'GET' : 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json',
            },
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
            signal: AbortSignal.timeout(30_000),
        }
    );
    const data = await response.json();
    return { data, status: response.status };
}

export async function loadCredentialReview(request: Request, path: string) {
    const { session, headers } = await requireAuth(request);
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);
    headers.set('Cache-Control', 'private, no-store');
    headers.set('Referrer-Policy', 'no-referrer');
    const result = await backend(path, session!.access_token);
    return json(
        { state: result.data, csrfToken },
        { headers, status: result.status }
    );
}

export async function submitCredentialReview(request: Request, path: string) {
    const { session, headers } = await requireAuth(request);
    const form = await request.formData();
    const failure = await csrfFailureResponse(request, form);
    if (failure) {
        for (const cookie of headers.getSetCookie())
            failure.headers.append('Set-Cookie', cookie);
        return failure;
    }
    headers.set('Cache-Control', 'private, no-store');
    let body: unknown;
    try {
        body = JSON.parse(String(form.get('payload') || '{}'));
    } catch {
        return json({ error: 'Invalid request.' }, { status: 400, headers });
    }
    const result = await backend(path, session!.access_token, body);
    return json(
        result.status < 400
            ? { saved: true }
            : { error: result.data.detail || 'Could not save this decision.' },
        { headers, status: result.status }
    );
}
