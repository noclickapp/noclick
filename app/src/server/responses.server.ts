// The answers the app's server gives of its own, in the shape NoClick's API uses for errors, so the SDK in the browser
// raises them as the errors it already knows (`Unauthenticated` for a 401, and so on).

export interface ApiErrorBody {
    type: string;
    message: string;
    next_step?: string;
    [detail: string]: unknown;
}

const NOT_STORED = { 'cache-control': 'no-store' };

export function apiError(status: number, error: ApiErrorBody, headers: Record<string, string> = {}): Response {
    return Response.json({ error }, { status, headers: { ...NOT_STORED, ...headers } });
}

export function plainText(status: number, text: string): Response {
    return new Response(text, { status, headers: { ...NOT_STORED, 'content-type': 'text/plain; charset=utf-8' } });
}

/** Paths the key proxy answers, where errors are the API's JSON rather than a page. */
export function isApiPath(pathname: string): boolean {
    return pathname === '/api' || pathname.startsWith('/api/');
}
