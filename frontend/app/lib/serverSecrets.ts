import crypto from 'node:crypto';

let developmentSecret: string | undefined;

/**
 * Return an operator-provided server secret, failing closed in production.
 * Development gets one process-local random value so source code never ships a
 * universal cookie-signing key.
 */
export function getServerSecret(primary = 'SESSION_SECRET'): string {
    const configured =
        process.env[primary] ||
        (primary === 'SESSION_SECRET' ? undefined : process.env.SESSION_SECRET);
    if (configured) return configured;

    if (process.env.NODE_ENV === 'production') {
        const names =
            primary === 'SESSION_SECRET'
                ? 'SESSION_SECRET'
                : `${primary} or SESSION_SECRET`;
        throw new Error(`${names} must be configured`);
    }

    developmentSecret ??= crypto.randomBytes(32).toString('base64url');
    return developmentSecret;
}

/** Derive a purpose-specific cookie signing secret. */
export function getCookieSecret(purpose: string): string {
    return crypto
        .createHmac('sha256', getServerSecret())
        .update(`noclick-cookie:${purpose}`)
        .digest('base64url');
}
