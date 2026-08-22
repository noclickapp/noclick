/**
 * Parse a same-origin OAuth setup form.
 *
 * Custom OAuth client secrets must arrive in a POST body, never in the URL,
 * because URLs are routinely retained by browser history, proxies, and access
 * logs. The Origin check prevents another site from silently starting a flow
 * in the user's browser.
 */
export async function oauthPostFormData(request: Request): Promise<FormData> {
    const requestOrigin = new URL(request.url).origin;
    const origin = request.headers.get('Origin');

    let submittedOrigin: string | null = null;
    try {
        submittedOrigin = origin ? new URL(origin).origin : null;
    } catch {
        submittedOrigin = null;
    }

    if (submittedOrigin !== requestOrigin) {
        throw new Response('Invalid OAuth request origin', { status: 403 });
    }

    return request.formData();
}

export function oauthFormString(
    formData: FormData,
    name: string
): string | null {
    const value = formData.get(name);
    return typeof value === 'string' ? value : null;
}
