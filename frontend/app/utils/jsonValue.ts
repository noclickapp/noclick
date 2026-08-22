import type { JsonObject, JsonValue } from '~/components/workflow/nodes/types';

/** Runtime guard for values crossing JSON/socket boundaries. */
export function isJsonValue(value: unknown): value is JsonValue {
    if (
        value === null ||
        typeof value === 'string' ||
        typeof value === 'boolean' ||
        typeof value === 'number'
    ) {
        return true;
    }
    if (Array.isArray(value)) return value.every(isJsonValue);
    if (typeof value !== 'object') return false;
    return Object.values(value).every(isJsonValue);
}

export function isJsonObject(value: unknown): value is JsonObject {
    return !!value && !Array.isArray(value) && isJsonValue(value);
}
