import crypto from 'crypto';

const STATE_MAX_AGE_MS = 15 * 60 * 1000;

export interface AtlassianOAuthState {
    credentialName: string;
    scopes: string[];
    jiraSite?: string;
    appOrigin: string;
    nonce: string;
    timestamp: number;
}

function getStateSecret(): string {
    const secret = process.env.ATLASSIAN_CLIENT_SECRET;
    if (!secret) {
        throw new Error('ATLASSIAN_CLIENT_SECRET environment variable is required');
    }
    return secret;
}

function signPayload(payload: string): string {
    return crypto
        .createHmac('sha256', getStateSecret())
        .update(payload)
        .digest('base64url');
}

export function encodeAtlassianOAuthState(state: AtlassianOAuthState): string {
    const payload = Buffer.from(JSON.stringify(state)).toString('base64url');
    return `${payload}.${signPayload(payload)}`;
}

export function decodeAtlassianOAuthState(rawState: string): AtlassianOAuthState {
    const [payload, signature] = rawState.split('.');
    if (!payload || !signature) {
        throw new Error('Malformed state parameter');
    }

    const expectedSignature = signPayload(payload);
    const signatureBuffer = Buffer.from(signature);
    const expectedBuffer = Buffer.from(expectedSignature);
    if (
        signatureBuffer.length !== expectedBuffer.length ||
        !crypto.timingSafeEqual(signatureBuffer, expectedBuffer)
    ) {
        throw new Error('Invalid state signature');
    }

    const parsed = JSON.parse(Buffer.from(payload, 'base64url').toString('utf-8')) as AtlassianOAuthState;
    if (!parsed.appOrigin || !parsed.credentialName || !Array.isArray(parsed.scopes) || !parsed.timestamp) {
        throw new Error('Invalid state payload');
    }

    const ageMs = Date.now() - parsed.timestamp;
    if (ageMs < 0 || ageMs > STATE_MAX_AGE_MS) {
        throw new Error('Expired state parameter');
    }

    return parsed;
}
