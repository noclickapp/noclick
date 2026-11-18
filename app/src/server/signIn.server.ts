// Signing in: the owner's password checked, and anyone guessing it slowed, with nothing stored anywhere.
//
// What this does: every wrong password is answered only after WRONG_PASSWORD_DELAY_MS, and each copy of the server
// checks at most MAX_CHECKS_AT_ONCE passwords at a time; an attempt past that is turned away unchecked (429), the
// right password included. So one copy answers at most MAX_CHECKS_AT_ONCE wrong guesses a second, however many
// requests arrive at once.
// What it doesn't: remember anything between requests, or across copies. A host running ten copies allows ten times
// the guesses, and someone sending three attempts a second keeps every check busy, so the owner's own sign-in is
// refused for as long as they keep it up (README: "What the sign-in protects, and what it doesn't"). A long random
// APP_PASSWORD is what keeps guessing hopeless; this only slows it.
import { data, redirect, type RouterContextProvider } from 'react-router';
import { appConfigContext } from './config.server';
import { signedIn, signInCookie } from './session.server';

export const WRONG_PASSWORD_DELAY_MS = 1000;
export const MAX_CHECKS_AT_ONCE = 3;
/** A sign-in form is a password and a path; anything bigger is refused before it is read. */
export const MAX_FORM_BYTES = 8 * 1024;

export type PasswordVerdict = 'right' | 'wrong' | 'busy';

let checking = 0;

const encoder = new TextEncoder();

async function digest(text: string): Promise<Uint8Array> {
    return new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(text.normalize('NFC'))));
}

/** Whether two strings are equal, in time that depends only on their digests' length, never on where they differ. */
async function sameText(given: string, expected: string): Promise<boolean> {
    const [a, b] = await Promise.all([digest(given), digest(expected)]);
    let difference = 0;
    for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
    return difference === 0;
}

const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Checks `given` against the owner's password: 'busy' when too many checks are under way to take another. */
export async function checkPassword(given: string, expected: string): Promise<PasswordVerdict> {
    if (checking >= MAX_CHECKS_AT_ONCE) return 'busy';
    checking++;
    try {
        if (await sameText(given, expected)) return 'right';
        await pause(WRONG_PASSWORD_DELAY_MS);
        return 'wrong';
    } finally {
        checking--;
    }
}

/** The fields of a small form post (url-encoded or multipart), or null when it is bigger than MAX_FORM_BYTES or not
 *  a form. Read with a limit, so a huge body costs the server nothing. */
export async function readSmallForm(request: Request): Promise<FormData | null> {
    const type = request.headers.get('content-type') ?? '';
    if (!/^(application\/x-www-form-urlencoded|multipart\/form-data)\b/i.test(type)) return null;
    if (Number(request.headers.get('content-length') ?? 0) > MAX_FORM_BYTES || !request.body) return null;
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_FORM_BYTES) {
            await reader.cancel();
            return null;
        }
        chunks.push(value);
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
        body.set(chunk, offset);
        offset += chunk.byteLength;
    }
    try {
        return await new Response(body, { headers: { 'content-type': type } }).formData();
    } catch {
        return null;
    }
}

/**
 * Where to send the owner after signing in: `next` when it is a path on this site, else `/`. What is judged is the
 * address actually sent, after the URL parser has resolved its dot segments (`/.//evil.example` resolves to
 * `//evil.example`), and it is refused if a browser could read it as another site: starting `//` or `/\`, or
 * resolving anywhere but this site. Control characters, which a browser strips, are refused before parsing.
 */
export function safeNext(next: FormDataEntryValue | string | null | undefined): string {
    if (typeof next !== 'string' || !next.startsWith('/') || /[\\\u0000-\u001f\u007f]/.test(next)) return '/';
    const base = 'https://app.invalid';
    let sent: string;
    try {
        const url = new URL(next, base);
        if (url.origin !== base || url.pathname === '/login') return '/';
        sent = url.pathname + url.search + url.hash;
    } catch {
        return '/';
    }
    if (sent.startsWith('//') || sent.startsWith('/\\') || new URL(sent, base).origin !== base) return '/';
    return sent;
}

type RouteArgs = { request: Request; context: Readonly<RouterContextProvider> };

/** The sign-in page's loader: an owner already signed in goes on to `next`. */
export async function sendSignedInOn({ request, context }: RouteArgs): Promise<null> {
    if (await signedIn(request, context.get(appConfigContext))) throw redirect(safeNext(new URL(request.url).searchParams.get('next')));
    return null;
}

/** The sign-in page's action: the password checked, then a session cookie and `next`, or why not. */
export async function signIn({ request, context }: RouteArgs) {
    const config = context.get(appConfigContext);
    const form = await readSmallForm(request);
    if (!form) return data({ error: 'That sign-in didn’t come from this page’s form.' }, { status: 400 });
    const password = form.get('password');
    const verdict = await checkPassword(typeof password === 'string' ? password : '', config.password);
    if (verdict === 'busy') {
        return data(
            { error: 'Too many sign-in attempts are under way. Wait a few seconds, then try again.' },
            { status: 429, headers: { 'retry-after': '2' } },
        );
    }
    if (verdict === 'wrong') return data({ error: 'That password isn’t right.' }, { status: 401 });
    return redirect(safeNext(form.get('next')), { headers: { 'set-cookie': await signInCookie(request, config) } });
}
