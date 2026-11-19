// How a value read out of a resource (a database row, a query's result) reads
// on a page: NULL as itself, bytes by their size, JSON compact in a cell and
// indented in full, numbers aligned; and which columns look secret, whose
// values a page hides until asked. Hiding is display-only: the data is as it
// was, and a download holds every value.

/** A column's last word that marks its values as secret: `api_key`, `accessToken`, `password_hash`, `otp_code`. */
const SECRET_WORDS = new Set(['token', 'secret', 'password', 'passwd', 'pwd', 'passphrase', 'hash', 'key', 'apikey', 'otp', 'code', 'passcode']);
/** A `…_code` that names a public value, not a secret one. */
const PUBLIC_CODES = new Set(['country', 'currency', 'zip', 'postal', 'area', 'language', 'lang', 'locale', 'status', 'error', 'http', 'response', 'exit', 'color', 'iso']);
/** Columns of the sign-in tables NoClick generates whose names don't say they're secret. */
const SIGN_IN_SECRETS: Record<string, readonly string[]> = { auth_verifications: ['value'] };

/** `accessToken` → `['access', 'token']`, `password_hash` → `['password', 'hash']`. */
function words(name: string): string[] {
    return name
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter(Boolean);
}

/** Whether a column's values are hidden until asked: its name ends in a secret word, or it's a sign-in table's secret. */
export function isSecretColumn(column: string, table?: string): boolean {
    const bare = table?.split('.').pop()?.toLowerCase();
    if (bare && SIGN_IN_SECRETS[bare]?.includes(column.toLowerCase())) return true;
    const parts = words(column);
    const last = parts.at(-1);
    if (!last || !SECRET_WORDS.has(last)) return false;
    return !(last === 'code' && parts.length > 1 && PUBLIC_CODES.has(parts.at(-2)!));
}

export const isBinaryType = (type: string | undefined) => !!type && /\b(blob|bytea|binary|varbinary)\b/i.test(type);
export const isNumericType = (type: string | undefined) => !!type && /\b(int\w*|integer|real|float\d*|double|numeric|decimal|number|serial|bigserial|smallserial|money)\b/i.test(type);

/** The bytes a value that travelled as base64 holds. */
export function binarySize(base64: string): number {
    const body = base64.replace(/\s/g, '');
    return Math.floor((body.length * 3) / 4) - (body.endsWith('==') ? 2 : body.endsWith('=') ? 1 : 0);
}

export type CellKind = 'null' | 'binary' | 'number' | 'boolean' | 'json' | 'text';

export interface ShownValue {
    kind: CellKind;
    /** One line, for a cell. */
    text: string;
    /** In full, for a record's page: JSON indented, text as it is. */
    full: string;
}

/** Text that is a JSON object or array, parsed; anything else null. */
function parsedJson(text: string): unknown {
    const trimmed = text.trim();
    if (!/^[[{]/.test(trimmed)) return null;
    try {
        return JSON.parse(trimmed);
    } catch {
        return null;
    }
}

/** A value as a page shows it, by what it is and its column's type. */
export function shownValue(value: unknown, type?: string): ShownValue {
    if (value === null || value === undefined) return { kind: 'null', text: 'NULL', full: 'NULL' };
    if (typeof value === 'string' && isBinaryType(type)) {
        const size = binarySize(value);
        const text = `${size.toLocaleString('en-US')} ${size === 1 ? 'byte' : 'bytes'}`;
        return { kind: 'binary', text, full: `${text} of binary data` };
    }
    if (typeof value === 'number' || typeof value === 'bigint') return { kind: 'number', text: String(value), full: String(value) };
    if (typeof value === 'boolean') return { kind: 'boolean', text: String(value), full: String(value) };
    if (typeof value === 'object') return { kind: 'json', text: JSON.stringify(value), full: JSON.stringify(value, null, 2) };
    const text = String(value);
    const json = parsedJson(text);
    if (json !== null) return { kind: 'json', text: text.replace(/\s*\n\s*/g, ' '), full: JSON.stringify(json, null, 2) };
    return { kind: isNumericType(type) && text !== '' && !Number.isNaN(Number(text)) ? 'number' : 'text', text: text.replace(/\s*\n\s*/g, ' '), full: text };
}

/**
 * A timestamp that names its zone as the reader's own time ("Oct 14, 2026, 9:12 AM"), or null: one without a zone
 * could be anyone's time, so it isn't converted.
 */
export function localTime(value: unknown): string | null {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}.*(Z|[+-]\d{2}(:?\d{2})?)$/.test(value)) return null;
    const at = Date.parse(value.includes('T') ? value : value.replace(' ', 'T'));
    if (Number.isNaN(at)) return null;
    return new Date(at).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}
