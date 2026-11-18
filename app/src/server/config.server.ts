// The app's settings: environment variables, read here and nowhere else (test/secrets.test.ts holds every other module
// to that). A `.server` module never reaches the browser: the build refuses client code that imports one.
import { DEFAULT_BASE_URL } from 'noclick';
import { createContext } from 'react-router';
import { isLoopbackHost } from './origin.server';

/** What the app runs with, except the NoClick key, which only `noclickApiKey()` hands out. */
export interface AppConfig {
    /** The owner's password for this deployment. */
    password: string;
    /** Signs the session cookie. */
    sessionSecret: string;
    /** NoClick's API, without a trailing slash. */
    apiUrl: string;
}

/** A setting that is missing or unusable: its name, what is wrong and how to fix it. Never its value. */
export interface ConfigProblem {
    name: string;
    problem: string;
    fix: string;
}

export type ConfigCheck = { ok: true; config: AppConfig } | { ok: false; problems: ConfigProblem[] };

export const MIN_PASSWORD_LENGTH = 12;
export const MIN_SESSION_SECRET_LENGTH = 32;
/** A key is printable ASCII with no spaces: all a header value can carry whole. */
const KEY_CHARACTERS = /^[\x21-\x7e]+$/;

type Environment = Record<string, string | undefined>;

/** The server's environment variables (`process.env`, which Node and runtimes compatible with it fill). */
function environment(): Environment {
    return (globalThis as { process?: { env?: Environment } }).process?.env ?? {};
}

/** The config the gate checked, for the loaders and actions that run after it (`context.get(appConfigContext)`). */
export const appConfigContext = createContext<AppConfig>();

/** Every setting, checked; the problems name each one that is missing or unusable, never a value. */
export function checkConfig(env: Environment = environment()): ConfigCheck {
    const problems: ConfigProblem[] = [];

    const key = env.NOCLICK_API_KEY ?? '';
    if (!key.trim()) {
        problems.push({
            name: 'NOCLICK_API_KEY',
            problem: 'is not set.',
            fix: 'Create a secret key in NoClick’s developer console (https://noclick.com/dashboard/developers) and set it here. The app acts in your account with it.',
        });
    } else if (!KEY_CHARACTERS.test(key)) {
        // Sent as a header, where a line break or a space would end it early (and the error would quote it).
        problems.push({
            name: 'NOCLICK_API_KEY',
            problem: 'has a space, a line break or another character a key never has.',
            fix: 'Set it to the key alone, on one line, with nothing around it (a .env file saved with Windows line endings adds one).',
        });
    }

    const password = env.APP_PASSWORD ?? '';
    if (!password) {
        problems.push({
            name: 'APP_PASSWORD',
            problem: 'is not set.',
            fix: `Set the password you will sign in to this app with: at least ${MIN_PASSWORD_LENGTH} characters, best random (openssl rand -base64 18 makes one).`,
        });
    } else if ([...password].length < MIN_PASSWORD_LENGTH) {
        problems.push({
            name: 'APP_PASSWORD',
            problem: `is shorter than ${MIN_PASSWORD_LENGTH} characters.`,
            fix: `Use at least ${MIN_PASSWORD_LENGTH} characters, best random (openssl rand -base64 18 makes one): the password is all that keeps others out.`,
        });
    }

    const sessionSecret = env.SESSION_SECRET ?? '';
    if (sessionSecret.length < MIN_SESSION_SECRET_LENGTH) {
        problems.push({
            name: 'SESSION_SECRET',
            problem: sessionSecret ? `is shorter than ${MIN_SESSION_SECRET_LENGTH} characters.` : 'is not set.',
            fix: `Set a random string of at least ${MIN_SESSION_SECRET_LENGTH} characters (openssl rand -base64 48 makes one). It signs the sign-in cookie; changing it signs everyone out.`,
        });
    }

    const apiUrl = apiUrlOf(env.NOCLICK_API_URL);
    if (typeof apiUrl !== 'string') problems.push(apiUrl);

    if (problems.length > 0 || typeof apiUrl !== 'string') return { ok: false, problems };
    return { ok: true, config: { password, sessionSecret, apiUrl } };
}

/** `NOCLICK_API_URL` as the base the proxy forwards to, or why it can't be. */
function apiUrlOf(value: string | undefined): string | ConfigProblem {
    const raw = value?.trim();
    if (!raw) return DEFAULT_BASE_URL;
    const unusable = (problem: string): ConfigProblem => ({
        name: 'NOCLICK_API_URL',
        problem,
        fix: `Leave it unset to use ${DEFAULT_BASE_URL}, or set the https address of the NoClick API to use.`,
    });
    let url: URL;
    try {
        url = new URL(raw);
    } catch {
        return unusable('is not a URL.');
    }
    if (url.username || url.password || url.search || url.hash) {
        return unusable('must be a plain address, with no sign-in details, query or fragment.');
    }
    // The key travels with every request, so never in the clear past this machine.
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopbackHost(url.hostname))) {
        return unusable('must use https (plain http only for an API on this machine).');
    }
    return `${url.origin}${url.pathname}`.replace(/\/+$/, '');
}

/** The NoClick key. Only the key proxy and the server client call this (test/secrets.test.ts guards against others). */
export function noclickApiKey(env: Environment = environment()): string {
    const key = env.NOCLICK_API_KEY ?? '';
    // Never a value in the message: the gate has already refused requests while the key is unusable.
    if (!KEY_CHARACTERS.test(key)) throw new Error('NOCLICK_API_KEY is not set, or not one line of printable characters.');
    return key;
}
