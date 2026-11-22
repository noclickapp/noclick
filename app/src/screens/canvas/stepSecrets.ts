// A step's settings without its secrets, for what leaves the canvas as text (a copy on the clipboard, a workflow saved
// to a file). The same rule the platform reads a workflow by, so what a copy carries is what `GET
// /v1/workflows/{id}/graph` would show of the step: a setting is a secret when its schema marks it (`writeOnly`, a
// password format or widget) or its name does (`api_key`, `client_secret`, `password`; never an address such as
// `token_url`), at any depth; a name/value row (a request's headers, query and form fields) and an entry of a map of
// headers when the name is `Authorization`, `Cookie`, `Set-Cookie` or `Proxy-Authorization` or holds `key`, `token` or
// `secret`. A yes or no is never one, and the accounts a step holds (`credentialIds`) are references, not secrets.

const SECRET_FIELD = /(?:^|_)(?:api_?key|key|token|secret|password|passwd|pat)(?:_|$)/i;
const ADDRESS_FIELD = /url|uri|host|domain|endpoint/i;
const SECRET_HEADERS = new Set(['authorization', 'cookie', 'set-cookie', 'proxy-authorization']);
const SECRET_WORDS = ['key', 'token', 'secret'];
const CONNECTIONS = 'credentialIds';

type Json = Record<string, unknown>;

const isObject = (value: unknown): value is Json => !!value && typeof value === 'object' && !Array.isArray(value);

/** A field whose name says it holds a secret. */
function secretFieldName(name: string): boolean {
    return SECRET_FIELD.test(name) && !ADDRESS_FIELD.test(name);
}

/** A header, map entry or name/value row that holds a secret, by its name. */
function secretName(name: unknown): boolean {
    const lowered = String(name ?? '').trim().toLowerCase();
    return SECRET_HEADERS.has(lowered) || SECRET_WORDS.some((word) => lowered.includes(word));
}

/** A field its schema marks as a secret. */
function markedSecret(prop: unknown): boolean {
    if (!isObject(prop)) return false;
    return prop.writeOnly === true || prop.format === 'password' || prop['ui:widget'] === 'password';
}

/** A name/value row's name (`{key|name, value}`), else null. */
function rowName(row: unknown): string | null {
    if (!isObject(row)) return null;
    const name = row.key ?? row.name;
    return typeof name === 'string' ? name : null;
}

/** `value` without the secrets inside it, judged by name; `under` is the key it's kept under. */
function withoutNested(value: unknown, under: string): unknown {
    if (Array.isArray(value)) {
        return value.map((row) => {
            const name = rowName(row);
            if (name !== null && isObject(row) && 'value' in row) {
                if (!secretName(name) || typeof row.value === 'boolean') return row;
                return Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'value'));
            }
            return withoutNested(row, under);
        });
    }
    if (!isObject(value)) return value;
    const headers = under.toLowerCase().includes('header');
    const out: Json = {};
    for (const [key, inner] of Object.entries(value)) {
        const secret = typeof inner !== 'boolean' && (headers ? secretName(key) : secretFieldName(key));
        if (!secret) out[key] = withoutNested(inner, key);
    }
    return out;
}

/** The properties of a step's settings as its type's schema declares them: its operation's, or each operation's where
 *  none is chosen or the schema names none for it; none where the schema isn't known. */
function declaredProps(schema: unknown, operation: unknown): Json[] {
    if (!isObject(schema)) return [];
    const defs = isObject(schema.$defs) ? schema.$defs : {};
    const resolve = (part: unknown): Json | null => {
        if (!isObject(part)) return null;
        const ref = typeof part.$ref === 'string' && part.$ref.startsWith('#/$defs/') ? defs[part.$ref.slice('#/$defs/'.length)] : null;
        return isObject(ref) ? ref : part;
    };
    const root = resolve(isObject(schema.properties) && schema.properties.config ? schema.properties.config : schema);
    if (!root) return [];
    const propsOf = (option: Json): Json => (isObject(option.properties) ? option.properties : {});
    const options = (Array.isArray(root.oneOf) ? root.oneOf : Array.isArray(root.anyOf) ? root.anyOf : []).map(resolve).filter(isObject);
    if (!options.length) return [propsOf(root)];
    const named = (option: Json): unknown => {
        const prop = propsOf(option).operation;
        return isObject(prop) ? (prop.const ?? (Array.isArray(prop.enum) && prop.enum.length === 1 ? prop.enum[0] : undefined)) : undefined;
    };
    const chosen = typeof operation === 'string' ? options.filter((option) => named(option) === operation) : [];
    return (chosen.length ? chosen : options).map(propsOf);
}

/** `settings` (a step's saved settings, its operation and accounts beside them) without their secrets. `schema` is the
 *  step type's settings schema where it's known; without it, names alone decide. */
export function withoutSecrets(settings: Record<string, unknown>, schema?: unknown): Record<string, unknown> {
    const declared = declaredProps(schema, settings.operation);
    const out: Json = {};
    for (const [key, value] of Object.entries(settings)) {
        if (key === CONNECTIONS) out[key] = value;
        else if (typeof value !== 'boolean' && (secretFieldName(key) || declared.some((props) => markedSecret(props[key])))) continue;
        else out[key] = withoutNested(value, key);
    }
    return out;
}
