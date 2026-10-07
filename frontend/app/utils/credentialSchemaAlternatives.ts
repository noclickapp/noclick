// Finds credential models inside generated nullable and discriminated unions.
// Form, metadata, and canvas selection readers share this leaf without rewriting schemas.
type SchemaObject = Record<string, any>;

function isSchemaObject(value: unknown): value is SchemaObject {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function resolveLocalRef(root: SchemaObject, ref: string): unknown {
    if (!/^#\/(\$defs|definitions)\//.test(ref)) return undefined;
    let value: unknown = root;
    for (const part of ref.slice(2).split('/')) {
        if (/~(?:[^01]|$)/.test(part)) return undefined;
        const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
        if (!isSchemaObject(value) || !Object.prototype.hasOwnProperty.call(value, key)) return undefined;
        value = value[key];
    }
    return value;
}

export interface CredentialSchemaAlternative {
    schema: SchemaObject;
    definitionName?: string;
}

/** Return concrete credential models in schema order, without mutating them.
 * Only credential alternatives are traversed; field schemas and discriminator mappings are not extra credential choices. */
export function collectCredentialAlternatives(rootSchema: unknown): CredentialSchemaAlternative[] {
    if (!isSchemaObject(rootSchema)) return [];
    const stack: Array<{ schema: unknown; definitionName?: string }> = [{ schema: rootSchema.properties?.credentials }];
    const seen = new Set<SchemaObject>();
    const result: CredentialSchemaAlternative[] = [];

    while (stack.length) {
        const { schema, definitionName } = stack.pop()!;
        if (!isSchemaObject(schema) || seen.has(schema)) continue;
        seen.add(schema);
        if (schema.type === 'null') continue;

        if (typeof schema.$ref === 'string') {
            const name = schema.$ref.split('/').pop()!.replace(/~1/g, '/').replace(/~0/g, '~');
            stack.push({ schema: resolveLocalRef(rootSchema, schema.$ref), definitionName: name });
            continue;
        }
        if ('anyOf' in schema || 'oneOf' in schema) {
            const alternatives = [schema.anyOf, schema.oneOf]
                .flatMap(value => Array.isArray(value) ? value : []);
            for (let i = alternatives.length - 1; i >= 0; i--) stack.push({ schema: alternatives[i] });
            continue;
        }
        if ((schema.type === undefined || schema.type === 'object') && isSchemaObject(schema.properties)) {
            if (['title', 'description', 'x-oauth-provider'].some(key => schema[key] != null && typeof schema[key] !== 'string')) continue;
            const credentialType = schema.properties.credential_type?.const;
            if (credentialType !== undefined && typeof credentialType !== 'string') continue;
            result.push({ schema, definitionName });
        }
    }
    return result;
}

export function collectCredentialSchemas(rootSchema: unknown): SchemaObject[] {
    return collectCredentialAlternatives(rootSchema).map(alternative => alternative.schema);
}
