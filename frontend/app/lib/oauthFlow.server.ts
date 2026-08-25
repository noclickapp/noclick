import crypto from 'node:crypto';
import { createCookie, redirect } from 'react-router';
import { getCookieSecret, getServerSecret } from './serverSecrets';
import { isTrustedAppOrigin } from './trustedAppOrigin.server';

const MAX_STATE_AGE_MS = 15 * 60 * 1000;

function providerFrom(
    pathname: string,
    suffix: 'authorize' | 'callback'
): string {
    const match = pathname.match(
        new RegExp(`^/api/auth/([^/.]+)(?:[/.])${suffix}$`)
    );
    if (!match || !/^[a-z0-9_-]+$/i.test(match[1])) {
        throw new Response('Invalid OAuth route', { status: 400 });
    }
    return match[1].toLowerCase();
}

function stateCookie(provider: string) {
    return createCookie(`nc_oauth_${provider}`, {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax',
        path: `/api/auth/${provider}`,
        maxAge: MAX_STATE_AGE_MS / 1000,
        secrets: [getCookieSecret(`oauth-binding:${provider}`)],
    });
}

function stateKey(): Buffer {
    return crypto
        .createHash('sha256')
        .update(`noclick-oauth-state:${getServerSecret()}`)
        .digest();
}

function sealState(rawState: string): string {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', stateKey(), iv);
    const plaintext = JSON.stringify({ state: rawState, issuedAt: Date.now() });
    const ciphertext = Buffer.concat([
        cipher.update(plaintext, 'utf8'),
        cipher.final(),
    ]);
    return [iv, ciphertext, cipher.getAuthTag()]
        .map((value) => value.toString('base64url'))
        .join('.');
}

function openState(sealed: string): string {
    const parts = sealed.split('.');
    if (parts.length !== 3) throw new Error('Malformed OAuth state');
    const [iv, ciphertext, tag] = parts.map((value) =>
        Buffer.from(value, 'base64url')
    );
    const decipher = crypto.createDecipheriv('aes-256-gcm', stateKey(), iv);
    decipher.setAuthTag(tag);
    const parsed = JSON.parse(
        Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString(
            'utf8'
        )
    ) as { state?: string; issuedAt?: number };
    if (
        typeof parsed.state !== 'string' ||
        typeof parsed.issuedAt !== 'number' ||
        parsed.issuedAt > Date.now() + 30_000 ||
        Date.now() - parsed.issuedAt > MAX_STATE_AGE_MS
    ) {
        throw new Error('Expired OAuth state');
    }
    return parsed.state;
}

function stateDigest(sealed: string): string {
    return crypto.createHash('sha256').update(sealed).digest('base64url');
}

/** Redirect to a provider with encrypted state bound to this browser. */
export async function oauthRedirect(
    request: Request,
    target: string,
    init?: ResponseInit
): Promise<Response> {
    const requestUrl = new URL(request.url);
    const provider = providerFrom(requestUrl.pathname, 'authorize');
    const providerUrl = new URL(target);
    const rawState = providerUrl.searchParams.get('state');
    if (!rawState)
        throw new Response('OAuth state was not generated', { status: 500 });

    const sealedState = sealState(rawState);
    providerUrl.searchParams.set('state', sealedState);
    const response = redirect(providerUrl.toString(), init);
    const bindingCookie = stateCookie(provider);
    const previous = await bindingCookie.parse(request.headers.get('Cookie'));
    const bindings = (Array.isArray(previous) ? previous : [previous])
        .filter((value): value is string => typeof value === 'string')
        .slice(-4);
    bindings.push(stateDigest(sealedState));
    response.headers.append(
        'Set-Cookie',
        await bindingCookie.serialize(bindings)
    );
    response.headers.set('Cache-Control', 'no-store');
    response.headers.set('Referrer-Policy', 'no-referrer');
    return response;
}

function trustedBounceOrigin(rawState: string): string | null {
    try {
        const value = JSON.parse(
            Buffer.from(rawState, 'base64url').toString('utf8')
        ) as { appOrigin?: string; mainOrigin?: string };
        const origin = value.appOrigin || value.mainOrigin;
        return origin && isTrustedAppOrigin(origin)
            ? new URL(origin).origin
            : null;
    } catch {
        return null;
    }
}

/**
 * Validate the browser binding and return a URL containing the route's original
 * (decrypted) state. Error-only callbacks without state remain user-friendly.
 * A trusted cross-origin popup callback is redirected to the bound application
 * origin with the encrypted state still intact.
 */
export async function oauthCallbackUrl(request: Request): Promise<URL> {
    const url = new URL(request.url);
    const provider = providerFrom(url.pathname, 'callback');
    const sealedState = url.searchParams.get('state');
    if (!sealedState) {
        if (url.searchParams.has('error') && !url.searchParams.has('code'))
            return url;
        throw new Response('Missing OAuth state', { status: 400 });
    }

    let rawState: string;
    try {
        rawState = openState(sealedState);
    } catch {
        throw new Response('Invalid or expired OAuth state', { status: 400 });
    }

    const expected = await stateCookie(provider).parse(
        request.headers.get('Cookie')
    );
    const actualDigest = stateDigest(sealedState);
    const expectedDigests = (
        Array.isArray(expected) ? expected : [expected]
    ).filter((value): value is string => typeof value === 'string');
    const bound = expectedDigests.some(
        (candidate) =>
            candidate.length === actualDigest.length &&
            crypto.timingSafeEqual(
                Buffer.from(candidate),
                Buffer.from(actualDigest)
            )
    );
    if (!bound) {
        const bounceOrigin = trustedBounceOrigin(rawState);
        if (!bounceOrigin || bounceOrigin === url.origin) {
            throw new Response(
                'OAuth session expired or did not originate here',
                {
                    status: 400,
                }
            );
        }
        const bounceUrl = new URL(url.pathname + url.search, bounceOrigin);
        throw redirect(bounceUrl.toString(), {
            headers: {
                'Cache-Control': 'no-store',
                'Referrer-Policy': 'no-referrer',
            },
        });
    }

    url.searchParams.set('state', rawState);
    return url;
}
