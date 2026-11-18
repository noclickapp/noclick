// The gate: what every request gets before the app answers it. One decision, `admit`, made in two places:
//   - the root route's middleware (`gate`), for every request to a route: pages, their data requests, the key proxy;
//   - the server entry (src/entry.server.tsx: `gateUnseen`), for what React Router answers before any middleware
//     runs: a method it doesn't take (405), a path no route matches (404; the `*` route matches every other path).
// In order: a setting missing or unusable gets the setup page (503); a request another site sent is refused when it
// would change something or reach the key proxy; without a session, the key proxy answers 401 and anything else goes
// to /login, which alone is open.
//
// Not seen by either: React Router's route manifest (`/__manifest`, which lists the app's routes and their public
// modules, the same for everyone), the static files in build/client, and the requests the Node server refuses before
// React Router (a URL whose percent-encoding doesn't decode, 400; a method fetch can't represent, such as TRACE, 500).
// test/served.test.ts pins what each of those answers.
import { createContext, data, redirect, redirectDocument, type MiddlewareFunction } from 'react-router';
import type { SetupData } from '@/screens/setup/SetupScreen';
import { appConfigContext, checkConfig, type AppConfig, type ConfigProblem } from './config.server';
import { crossSite, servedLocally } from './origin.server';
import { apiError, isApiPath, plainText } from './responses.server';
import { signedIn } from './session.server';
import { SETUP_HOW, setupApiError } from './setup.server';

export const LOGIN_PATH = '/login';
const SAFE_METHODS = new Set(['GET', 'HEAD']);

export type Admission =
    | { verdict: 'setup'; problems: ConfigProblem[] }
    | { verdict: 'cross-site' }
    | { verdict: 'signed-out' }
    | { verdict: 'open'; config: AppConfig };

/** What the gate decides for `request`, before anything else answers it. */
export async function admit(request: Request): Promise<Admission> {
    const check = checkConfig();
    if (!check.ok) return { verdict: 'setup', problems: check.problems };
    const { pathname } = new URL(request.url);
    // The key proxy serves this app's own pages only, so a link or embed from elsewhere is refused too.
    if ((isApiPath(pathname) || !SAFE_METHODS.has(request.method)) && crossSite(request)) return { verdict: 'cross-site' };
    // The sign-in page is open, as a page and as its data request.
    if (pathname === LOGIN_PATH || pathname === `${LOGIN_PATH}.data`) return { verdict: 'open', config: check.config };
    return (await signedIn(request, check.config)) ? { verdict: 'open', config: check.config } : { verdict: 'signed-out' };
}

function crossSiteRefusal(request: Request): Response {
    return isApiPath(new URL(request.url).pathname)
        ? apiError(403, { type: 'permission_denied', message: 'This app answers only its own pages, not other sites.' })
        : plainText(403, 'This app refuses requests that other sites make.');
}

function signedOutApiError(): Response {
    return apiError(401, {
        type: 'unauthenticated',
        message: 'You’re signed out of this app.',
        next_step: 'Open the app and sign in.',
        reason: 'signed_out',
    });
}

/** Where a signed-out request for `page` (a path and query) goes: /login, remembering a page it was reading. */
function signInAddress(method: string, page: string): string {
    return SAFE_METHODS.has(method) && page !== '/' ? `${LOGIN_PATH}?next=${encodeURIComponent(page)}` : LOGIN_PATH;
}

/** The page a request is for, with the page's own query: a data request's (`/agents.data`, `/_root.data` for `/`)
 *  without React Router's own parameters. */
function pageOf(url: URL): string {
    let path = url.pathname.replace(/\.data$/, '');
    if (path === '/_root') path = '/';
    const search = new URLSearchParams(url.search);
    search.delete('_routes');
    search.delete('index');
    const query = search.toString();
    return query ? `${path}?${query}` : path;
}

/**
 * The headers every answer gets: no page of this app's shown inside another site's (so nothing in it can be clicked
 * through a disguise), nothing sniffed as another type, nothing stored unless the answer says it may be (static
 * files are served before the gate and keep their caching), and, served anywhere but this machine, https only.
 */
export function withSecurityHeaders(request: Request, response: Response): Response {
    const headers = response.headers;
    headers.set('x-frame-options', 'DENY');
    if (!headers.has('content-security-policy')) headers.set('content-security-policy', "frame-ancestors 'none'");
    headers.set('x-content-type-options', 'nosniff');
    if (!headers.has('cache-control')) headers.set('cache-control', 'no-store');
    if (!servedLocally(request)) headers.set('strict-transport-security', 'max-age=31536000');
    return response;
}

/** Set by the root's middleware as it judges a request, so the server entry doesn't judge that request again. */
export const gateRanContext = createContext<boolean>(false);

/** The root route's middleware, outermost: the security headers on every answer, the error pages' included. */
export const securityHeaders: MiddlewareFunction<Response> = async ({ request }, next) => withSecurityHeaders(request, await next());

/** The root route's middleware: the gate inside React Router, where its redirects reach a page's data requests too. */
export const gate: MiddlewareFunction<Response> = async ({ request, context }, next) => {
    context.set(gateRanContext, true);
    const admission = await admit(request);
    const url = new URL(request.url);
    const api = isApiPath(url.pathname);
    switch (admission.verdict) {
        case 'setup':
            if (api) return setupApiError(admission.problems);
            // The root's error boundary draws the setup page, in the app's own look.
            throw data({ setup: admission.problems } satisfies SetupData, { status: 503 });
        case 'cross-site':
            return crossSiteRefusal(request);
        case 'signed-out':
            // A data request reaches the middleware as its page's address, still carrying React Router's own query.
            return api ? signedOutApiError() : redirect(signInAddress(request.method, pageOf(url)));
        case 'open':
            context.set(appConfigContext, admission.config);
            return next();
    }
};

/**
 * The gate's answer to a request React Router answered without running its middleware (the server entry calls this
 * for every document it renders and every data answer, and skips it where the middleware already ran): null when the
 * request may have React Router's answer. A data request is sent to load a document, which the gate then judges.
 */
export async function gateUnseen(request: Request, kind: 'document' | 'data'): Promise<Response | null> {
    const admission = await admit(request);
    const url = new URL(request.url);
    const api = isApiPath(url.pathname);
    switch (admission.verdict) {
        case 'open':
            return null;
        case 'cross-site':
            return crossSiteRefusal(request);
        case 'signed-out':
            if (api) return signedOutApiError();
            return kind === 'data' ? redirectDocument(signInAddress(request.method, pageOf(url))) : redirect(signInAddress(request.method, pageOf(url)));
        case 'setup':
            if (api) return setupApiError(admission.problems);
            if (kind === 'data') return redirectDocument(pageOf(url));
            // Only odd requests get here (a method no page takes, a path no route matches); a page gets the drawn one.
            return plainText(503, `This app isn’t set up yet: ${admission.problems.map((p) => `${p.name} ${p.problem}`).join(' ')} ${SETUP_HOW}`);
    }
}
