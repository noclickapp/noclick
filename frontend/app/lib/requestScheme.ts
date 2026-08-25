// Whether a request reached us over TLS. Lives outside csrf.server.ts because
// supabase.ts needs it too, and supabase.ts is in the CLIENT graph — importing a
// .server module from there fails the Remix vite build ("Server-only module
// referenced by client"). Nothing here is server-only: it reads a header and a URL.

/** Honors the proxy header first, since TLS usually terminates upstream and
 *  request.url is plain http:// behind it. */
export function requestIsHttps(request: Request): boolean {
    const forwarded = request.headers.get('X-Forwarded-Proto');
    if (forwarded) return forwarded.split(',')[0].trim() === 'https';
    return new URL(request.url).protocol === 'https:';
}
