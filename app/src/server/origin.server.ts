// Where a request came from: another site (refused for anything that changes state), and whether the app is being
// served on this machine (where the session cookie can't be Secure over plain http).

/** A name for this machine: localhost (and its subdomains), 127.0.0.0/8 or ::1. */
export function isLoopbackHost(hostname: string): boolean {
    const host = hostname.toLowerCase().replace(/^\[(.*)\]$/, '$1');
    return host === 'localhost' || host.endsWith('.localhost') || host === '::1' || /^127(?:\.\d{1,3}){3}$/.test(host);
}

/** Headers a proxy in front of the app adds: a request carrying any came from elsewhere, whatever its Host says. */
const FORWARDING_HEADERS = ['forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto', 'x-real-ip'];

/** A request a browser on this machine sent straight to the app. Anything else gets a Secure cookie. */
export function servedLocally(request: Request): boolean {
    return isLoopbackHost(new URL(request.url).hostname) && !FORWARDING_HEADERS.some((name) => request.headers.has(name));
}

/**
 * The app's own origin as the browser sees it: the request's, with the scheme a proxy in front says it took the
 * request over (`X-Forwarded-Proto`; a page on another site can't make the browser send that header).
 */
export function appOrigin(request: Request): string {
    const url = new URL(request.url);
    const forwarded = request.headers.get('x-forwarded-proto')?.split(',')[0].trim().toLowerCase();
    const scheme = forwarded === 'https' || forwarded === 'http' ? `${forwarded}:` : url.protocol;
    return `${scheme}//${url.host}`;
}

/**
 * A request a page on another site made the browser send. Browsers name the requesting site in `Sec-Fetch-Site`
 * (same-origin, same-site, cross-site, or none for one the person started, such as a typed address); older ones only
 * send `Origin`, compared here with the app's whole origin, scheme and port included. A request with neither
 * can't be told apart from a non-browser client here; the key proxy refuses it anyway (it needs the browser
 * client's bearer, which a navigation or an embed can't send).
 */
export function crossSite(request: Request): boolean {
    const site = request.headers.get('sec-fetch-site');
    if (site !== null) return site !== 'same-origin' && site !== 'none';
    const origin = request.headers.get('origin');
    if (origin === null) return false;
    try {
        return new URL(origin).origin !== appOrigin(request);
    } catch {
        // `Origin: null` (a sandboxed frame, a redirect across sites) is no origin of the app's.
        return true;
    }
}
