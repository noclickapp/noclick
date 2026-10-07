/** Diagnostic copies only; never use these projections for socket transport. */
import { ClientEventNames } from '~/types/socket-events.generated';

export const REDACTED_SOCKET_DATA = '[Sensitive socket data omitted]';
const OMITTED = '[Diagnostic value omitted]';
const MAX_DEPTH = 6;
const MAX_ITEMS = 50;
const MAX_NODES = 200;
const MAX_STRING = 1000;
const knownEvents = new Set<string>([
    ...Object.values(ClientEventNames), 'active_gen:token_progress',
    'workflow:node:output', 'workflow:node:state', 'workflow:started', 'workflow:complete',
]);

const sensitiveEventParts = new Set([
    'auth', 'oauth', 'credential', 'credentials', 'otp', 'password', 'token',
    'tokens', 'login', 'signin', 'callback', 'verification', 'verify', 'keys',
]);
const sensitiveKeys = new Set([
    'token', 'accesstoken', 'refreshtoken', 'idtoken', 'authtoken', 'bearertoken',
    'secret', 'clientsecret', 'password', 'clientpassword', 'apikey', 'apisecret',
    'authorization', 'cookie', 'setcookie', 'codeverifier', 'codechallenge',
    'authorizationcode', 'exchangeticket', 'otp', 'verificationcode',
    'redirecturi', 'callbackurl', 'credential', 'credentials', 'credentialdata',
    'privatekey', 'accesskey', 'secretkey', 'connectionstring', 'connectionurl',
    'signedurl',
]);
const authErrorCodes = new Set(['token_expired', 'token_invalid', 'auth_failed', 'missing_auth']);
const disconnectReasons = new Set(['io server disconnect', 'io client disconnect', 'ping timeout', 'transport close', 'transport error']);
const transportErrors = new Set(['xhr poll error', 'xhr post error', 'websocket error', 'timeout']);

export function diagnosticAuthErrorCode(value: unknown): string | undefined {
    return typeof value === 'string' && authErrorCodes.has(value) ? value : undefined;
}

export function diagnosticDisconnectReason(value: unknown): string {
    return typeof value === 'string' && disconnectReasons.has(value) ? value : OMITTED;
}

export function diagnosticTransportError(value: unknown): string | undefined {
    return typeof value === 'string' && transportErrors.has(value) ? value : undefined;
}

export function isSensitiveSocketEvent(eventName: string | undefined): boolean {
    // A generic response has no safe payload contract without its request context.
    if (typeof eventName !== 'string' || !eventName || eventName.length > 200 || eventName === 'response' || eventName === 'error') return true;
    if (eventName === 'active_gen:token_progress') return false;
    return eventName.toLowerCase().split(/[^a-z0-9]+/).some(part => sensitiveEventParts.has(part))
        || eventName === 'instance_smtp:set' || eventName === 'share:invite_link' || eventName === 'share:invite_accept'
        || eventName.startsWith('agent_share:') || eventName.startsWith('shared_agent:') || !knownEvents.has(eventName);
}

function isSensitiveKey(key: string): boolean {
    const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, '');
    return sensitiveKeys.has(normalized) || /(?:password|secret|apikey|token|cookie|authorization|privatekey|secretkey|otp)$/.test(normalized);
}

function safeString(value: string): string {
    return value.slice(0, MAX_STRING)
        .replace(/\b(?:Bearer|Basic)\s+[^\s,;]+/gi, '[Authorization omitted]')
        .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[Token omitted]')
        .replace(/https?:\/\/[^\s<>"']+/gi, url => /[?#@]/.test(url) ? '[Private URL omitted]' : url);
}

/** Bounded JSON-shaped copy; accessors, class instances and binary data are omitted. */
export function projectSocketDiagnostics(eventName: string | undefined, value: unknown): unknown {
    if (value === undefined) return undefined;
    if (isSensitiveSocketEvent(eventName)) return REDACTED_SOCKET_DATA;
    let remaining = MAX_NODES;
    const seen = new WeakSet<object>();
    const copy = (current: unknown, depth: number): unknown => {
        if (--remaining < 0 || depth > MAX_DEPTH) return OMITTED;
        if (current === null || typeof current === 'boolean') return current;
        if (typeof current === 'string') return safeString(current);
        if (typeof current === 'number') return Number.isFinite(current) ? current : OMITTED;
        if (typeof current !== 'object' || current === null) return OMITTED;
        if (seen.has(current)) return '[Circular diagnostic value]';
        if (ArrayBuffer.isView(current) || current instanceof ArrayBuffer) return '[Binary data omitted]';
        if (current instanceof Error) {
            const message = Object.getOwnPropertyDescriptor(current, 'message');
            return { name: 'Error', message: message && 'value' in message && typeof message.value === 'string'
                ? safeString(message.value) : OMITTED };
        }
        const isArray = Array.isArray(current);
        const prototype = Object.getPrototypeOf(current);
        if (!isArray && prototype !== Object.prototype && prototype !== null) return OMITTED;
        seen.add(current);
        const result: Record<string, unknown> | unknown[] = isArray ? [] : Object.create(null);
        const rowLabel = Object.getOwnPropertyDescriptor(current, 'key') ?? Object.getOwnPropertyDescriptor(current, 'name');
        const sensitiveRow = rowLabel && 'value' in rowLabel && typeof rowLabel.value === 'string'
            && (rowLabel.value.length > 128 || isSensitiveKey(rowLabel.value));
        const keys = isArray
            ? Array.from({ length: Math.min(current.length, MAX_ITEMS) }, (_, index) => String(index))
            : Object.keys(current).slice(0, MAX_ITEMS);
        for (const key of keys) {
            const descriptor = Object.getOwnPropertyDescriptor(current, key);
            if (!descriptor) continue;
            const safeKey = key.length > 128 ? '[Long key omitted]' : key;
            const projected = key.length > 128 ? OMITTED : isSensitiveKey(key) || (key === 'value' && sensitiveRow)
                ? REDACTED_SOCKET_DATA
                : 'value' in descriptor ? copy(descriptor.value, depth + 1) : OMITTED;
            if (isArray) (result as unknown[]).push(projected);
            else (result as Record<string, unknown>)[safeKey] = projected;
            if (remaining <= 0) break;
        }
        return result;
    };
    try {
        return copy(value, 0);
    } catch {
        return OMITTED;
    }
}

export function diagnosticSocketText(eventName: string | undefined, value: unknown): string | undefined {
    if (value === undefined) return undefined;
    const projected = projectSocketDiagnostics(eventName, value);
    if (typeof projected === 'string') return projected;
    if (projected && typeof projected === 'object' && 'message' in projected && typeof projected.message === 'string') {
        return projected.message;
    }
    return OMITTED;
}
