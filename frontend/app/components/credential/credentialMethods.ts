// The ways a node's app can be connected, read from its JSON schema: each credential class it accepts, humanized,
// in the order a person should meet them (a sign-in first, a key next, a sign-in that needs your own OAuth app last).
// NodeCredentials and the connect dialog read the same list, and `methodFromRequirement` puts each in the shape the
// public provide page gets from the backend, so one connect UI serves both.
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getCredentialTypeFromSchema } from '~/utils/credentialTypes';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import type { CredentialField } from './CredentialFieldInput';
import type { ProvideCredentialMethod } from './CredentialMethodConnect';

/** A JSON schema object as the generated node schemas have it, read field by field. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- generated JSON with no static shape
type Schema = Record<string, any>;

export interface CredentialRequirement {
    credential_type: string;
    label: string;
    description: string;
    schema?: Schema; // JSON Schema defining credential structure
}

const isOAuth = (credentialSchema: Schema | undefined): boolean => kindFromCredentialType(credentialSchema?.['x-credential-type']) === 'oauth';

/** The fields a credential class asks for, from its JSON schema. */
export function getFieldsFromSchema(credentialSchema: Schema | undefined): CredentialField[] {
    if (!credentialSchema?.properties) return [];
    const required = credentialSchema.required || [];
    return Object.entries(credentialSchema.properties as Record<string, Schema>)
        // A const (the class's own credential_type) has one possible value, so nobody is asked for it.
        .filter(([, prop]: [string, Schema]) => !prop['ui:hidden'] && !('const' in prop))
        .map(([name, prop]: [string, Schema]) => {
            const enumValues: string[] | undefined = prop.enum;
            const enumNames: string[] | undefined = prop.enumNames;
            return {
                name,
                label: prop.title || name,
                type: prop['ui:widget'] === 'password' ? 'password' : 'text',
                placeholder: prop['ui:placeholder'] || prop.placeholder,
                required: required.includes(name),
                // ui:help is the field's own guidance; the Pydantic description
                // is the fallback. A field-level x-credential-url says where
                // this one value comes from.
                description: prop['ui:help'] || prop.description,
                helpUrl: typeof prop['x-credential-url'] === 'string' && prop['x-credential-url'].startsWith('http') ? prop['x-credential-url'] : undefined,
                default: prop.default,
                options: Array.isArray(enumValues) ? enumValues.map((v, i) => ({ value: v, label: enumNames?.[i] ?? v })) : undefined,
            };
        });
}

/** OAuth first, then an API key, then a PAT, then the rest; an OAuth sign-in that needs your own app comes last. */
function priority(req: CredentialRequirement): number {
    if (isOAuth(req.schema)) return req.schema?.['x-oauth-requires-custom-client'] ? 4 : 0;
    const type = req.credential_type.toLowerCase();
    if (type.includes('api_key') || type.includes('apikey')) return 1;
    if (type.includes('pat') || type.includes('personal_access_token')) return 2;
    return 3;
}

/** Every credential class a node schema accepts, humanized and in order. `isVisible` hides a class pending approval. */
export function requirementsFromSchema(schemaData: Schema, isVisible: (credentialSchema: Schema) => boolean = () => true): CredentialRequirement[] {
    const credentialProp = schemaData?.properties?.credentials;
    if (!credentialProp || credentialProp.type === 'null') return [];
    const resolveRef = (ref: string) => {
        const path = ref.replace('#/$defs/', '');
        return schemaData.$defs?.[path] || schemaData.definitions?.[path];
    };
    // The label is humanized once here ('GoogleSheetsOAuth' → 'Google Sheets OAuth') so every downstream use reads
    // naturally.
    const requirement = (credSchema: Schema): CredentialRequirement => ({
        credential_type: getCredentialTypeFromSchema(credSchema),
        label: humanizeCredentialLabel(credSchema.title?.replace(/Credentials?$/, '') || 'Credential'),
        description: credSchema.description || '',
        schema: credSchema,
    });
    const out: CredentialRequirement[] = [];
    if (credentialProp.$ref) {
        const credSchema = resolveRef(credentialProp.$ref);
        if (credSchema) out.push(requirement(credSchema));
    } else if (credentialProp.anyOf) {
        // Union types (AirtablePATCredential | AirtableOAuthCredential): every non-null $ref.
        for (const entry of credentialProp.anyOf.filter((e: Schema) => e.$ref)) {
            const credSchema = resolveRef(entry.$ref);
            if (credSchema && isVisible(credSchema)) out.push(requirement(credSchema));
        }
    } else {
        out.push(requirement(credentialProp));
    }
    return out.sort((a, b) => priority(a) - priority(b));
}

/** The app a node connects, as the catalog names it ("Notion"); the schema's own title where the catalog isn't loaded. */
export function appNameOf(nodeType: string): string {
    const label = getNodeIconMeta(nodeType)?.label;
    if (label) return label;
    const title = NODE_SCHEMAS[nodeType]?.title;
    if (typeof title === 'string' && title.trim()) return title.replace(/\s*(Node\s+)?Configuration$/i, '').trim();
    return humanizeCredentialLabel(nodeType.replace(/^automation-/, '').replace(/-(.)/g, (_, c: string) => c.toUpperCase()).replace(/^./, (c) => c.toUpperCase()));
}

export function credentialRequirements(nodeType: string, isVisible?: (credentialSchema: Schema | undefined) => boolean): CredentialRequirement[] {
    const schemaData = NODE_SCHEMAS[nodeType];
    if (!schemaData) throw new Error(`No schema found for node type: ${nodeType}`);
    return requirementsFromSchema(schemaData, isVisible);
}

/** A schema requirement in the shape the provide page's backend methods have. */
export function methodFromRequirement(req: CredentialRequirement): ProvideCredentialMethod {
    const s: Schema = req.schema ?? {};
    const kind = kindFromCredentialType(s['x-credential-type']);
    return {
        credential_type: req.credential_type,
        label: req.label,
        description: req.description,
        credential_url: typeof s['x-credential-url'] === 'string' ? s['x-credential-url'] : null,
        instructions: typeof s['x-credential-instructions'] === 'string' ? s['x-credential-instructions'] : null,
        method_kind: kind,
        is_oauth: kind === 'oauth',
        oauth_provider: s['x-oauth-provider'] ?? null,
        oauth_scopes: s['x-oauth-scopes'] ?? [],
        oauth_user_scopes: s['x-oauth-user-scopes'] ?? [],
        supports_custom_client: s['x-oauth-supports-custom-client'] === true,
        requires_custom_client: s['x-oauth-requires-custom-client'] === true,
        oauth_redirect_uri: s['x-oauth-redirect-uri'] ?? null,
        credential_fields: kind === 'api_key' ? getFieldsFromSchema(s) : [],
    };
}
