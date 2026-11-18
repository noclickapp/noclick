// The owner's session: a signed cookie that says only that they signed in, and when. Nothing is kept on the server,
// so the app runs as many copies as a host likes; the flip side is that signing out ends the session in that browser
// only (a copied cookie lasts until it expires), and changing APP_PASSWORD or SESSION_SECRET ends every session.
import { createCookieSessionStorage, redirect, type RouterContextProvider, type SessionStorage } from 'react-router';
import { appConfigContext, type AppConfig } from './config.server';
import { servedLocally } from './origin.server';

export const SESSION_DAYS = 7;
const LIFETIME_S = SESSION_DAYS * 24 * 60 * 60;
/** How far ahead of this server's clock a sign-in time may be (another copy's clock). */
const CLOCK_SKEW_S = 60;

interface SessionData {
    /** When the owner signed in, in seconds since 1970. */
    signedInAt: number;
}

/** `__Host-` makes the browser keep the cookie for this host alone, only over https, for the whole site. */
export function cookieName(secure: boolean): string {
    return secure ? '__Host-noclick-app-session' : 'noclick-app-session';
}

const encoder = new TextEncoder();

/** The key the cookie is signed with: SESSION_SECRET, bound to the password, so changing either ends every session. */
async function signingSecret(config: AppConfig): Promise<string> {
    const key = await crypto.subtle.importKey('raw', encoder.encode(config.sessionSecret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const mac = await crypto.subtle.sign('HMAC', key, encoder.encode(`noclick app session\n${config.password}`));
    return Array.from(new Uint8Array(mac), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** The cookie storage for `request`: Secure (and `__Host-`) unless a browser on this machine is talking to the app. */
export async function sessionStorageFor(request: Request, config: AppConfig): Promise<SessionStorage<SessionData>> {
    const secure = !servedLocally(request);
    return createCookieSessionStorage<SessionData>({
        cookie: {
            name: cookieName(secure),
            httpOnly: true,
            secure,
            sameSite: 'lax',
            path: '/',
            maxAge: LIFETIME_S,
            secrets: [await signingSecret(config)],
        },
    });
}

/** Whether `request` carries a session: signed with this deployment's key, and signed in less than SESSION_DAYS ago. */
export async function signedIn(request: Request, config: AppConfig, now: number = Date.now()): Promise<boolean> {
    const storage = await sessionStorageFor(request, config);
    // A cookie whose signature doesn't verify reads as an empty session.
    const at: unknown = (await storage.getSession(request.headers.get('cookie'))).get('signedInAt');
    const nowS = Math.floor(now / 1000);
    return typeof at === 'number' && Number.isFinite(at) && at <= nowS + CLOCK_SKEW_S && nowS - at < LIFETIME_S;
}

/** The `Set-Cookie` that signs the owner in, from `now` for SESSION_DAYS. */
export async function signInCookie(request: Request, config: AppConfig, now: number = Date.now()): Promise<string> {
    const storage = await sessionStorageFor(request, config);
    const session = await storage.getSession();
    session.set('signedInAt', Math.floor(now / 1000));
    return storage.commitSession(session);
}

/** The `Set-Cookie` that removes the session cookie from this browser. */
export async function signOutCookie(request: Request, config: AppConfig): Promise<string> {
    const storage = await sessionStorageFor(request, config);
    return storage.destroySession(await storage.getSession(request.headers.get('cookie')));
}

/** The sign-out action: the cookie removed from this browser, and back to signing in. */
export async function signOut({ request, context }: { request: Request; context: Readonly<RouterContextProvider> }): Promise<Response> {
    return redirect('/login', { headers: { 'set-cookie': await signOutCookie(request, context.get(appConfigContext)) } });
}
