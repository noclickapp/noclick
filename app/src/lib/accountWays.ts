// The ways a step's app can be connected, read from its settings schema: each credential class it accepts, humanized,
// in the order a person should meet them (a sign-in first, a key next, a sign-in that needs your own OAuth app last);
// and whether the step runs with no account at all, on NoClick's own key. A step's account picker and a connect dialog
// read the same list, and `methodFromRequirement` puts each way in the shape a provide page gets from the API, so one
// connect UI serves both.
import { humanizeCredentialLabel } from '@/lib/credentialLabels';
import { kindFromBackendMethod, kindFromCredentialType } from '@/lib/credentialMethodKind';

/** A JSON schema object as step types' schemas have it, read field by field. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- generated JSON with no static shape
type Schema = Record<string, any>;

/** One credential field, as a form that asks for it draws it. */
export interface CredentialField {
    name: string;
    label: string;
    type: string;
    placeholder?: string;
    required: boolean;
    description?: string;
    /** Where this one value comes from, when the schema names it. */
    helpUrl?: string | null;
    default?: string;
    options?: Array<{ value: string; label: string }>;
}

/** One way of connecting an app, as the API describes it to a provide page (and as a schema's way in is put). */
export interface ProvideCredentialMethod {
    credential_type: string;
    label: string;
    /** Shown under the label in the method picker. */
    description?: string | null;
    /** "Get your API key here" deep link for the picker. */
    credential_url?: string | null;
    /** Where the values come from, in steps (the schema's x-credential-instructions). */
    instructions?: string | null;
    method_kind?: string | null;
    is_oauth: boolean;
    oauth_provider?: string | null;
    oauth_scopes?: string[];
    oauth_user_scopes?: string[];
    supports_custom_client?: boolean;
    requires_custom_client?: boolean;
    oauth_redirect_uri?: string | null;
    /** The requester brings its own OAuth app for this provider: the sign-in asks consent for it. */
    oauth_app?: boolean;
    agent_oauth_kind?: string | null;
    credential_fields: CredentialField[];
    /** A vendor MCP way in (kind `mcp`): the server it connects through. */
    mcp_server?: string | null;
}

export interface CredentialRequirement {
    credential_type: string;
    label: string;
    description: string;
    schema?: Schema; // JSON Schema defining credential structure
}

/** A credential class's own credential type: its `credential_type` constant, else its title lowercased. */
export function credentialTypeOfSchema(credSchema: Schema | undefined): string {
    return credSchema?.properties?.credential_type?.const || String(credSchema?.title ?? '').toLowerCase();
}

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

/** Where a way in stands among an app's: a sign-in first, then an API key, then a PAT, then the rest (a vendor's MCP
 *  server among them, a second way in); a sign-in that needs your own OAuth app later, and one still in preview last
 *  (shown only to accounts its flag lets in, while the provider reviews NoClick's app, so it may not work yet).
 *  Connections and a provide link order the same ways in by it. */
export function wayInRank(
    method: Parameters<typeof kindFromBackendMethod>[0] & Pick<ProvideCredentialMethod, 'credential_type' | 'requires_custom_client'> & { preview?: boolean }
): number {
    if (method.preview) return 5;
    const kind = kindFromBackendMethod(method);
    if (kind === 'oauth' || kind === 'agent_oauth') return method.requires_custom_client ? 4 : 0;
    const type = method.credential_type.toLowerCase();
    if (type.includes('api_key') || type.includes('apikey')) return 1;
    if (type.includes('pat') || type.includes('personal_access_token')) return 2;
    return 3;
}

const priority = (req: CredentialRequirement): number =>
    wayInRank({
        credential_type: req.credential_type,
        method_kind: kindFromCredentialType(req.schema?.['x-credential-type']),
        requires_custom_client: !!req.schema?.['x-oauth-requires-custom-client'],
        preview: !!req.schema?.['x-credential-hidden'],
    });

/** Every credential class a step type's schema accepts, humanized and in order. `isVisible` hides a class pending
 *  approval; `typeOf` reads a class's credential type (its constant, else its title, as `credentialTypeOfSchema`). */
export function requirementsFromSchema(
    schemaData: Schema,
    isVisible: (credentialSchema: Schema) => boolean = () => true,
    typeOf: (credentialSchema: Schema) => string = credentialTypeOfSchema
): CredentialRequirement[] {
    const credentialProp = schemaData?.properties?.credentials;
    if (!credentialProp || credentialProp.type === 'null') return [];
    const resolveRef = (ref: string) => {
        const path = ref.replace('#/$defs/', '');
        return schemaData.$defs?.[path] || schemaData.definitions?.[path];
    };
    // The label is humanized once here ('GoogleSheetsOAuth' → 'Google Sheets OAuth') so every downstream use reads
    // naturally.
    const requirement = (credSchema: Schema): CredentialRequirement => ({
        credential_type: typeOf(credSchema),
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
        mcp_server: typeof s['x-mcp-server'] === 'string' ? s['x-mcp-server'] : null,
    };
}

// ── running with no account ──────────────────────────────────────────────────

/** A step's operation and settings, as the checks below read them. */
export interface StepSettings {
    operation?: string;
    config?: Record<string, unknown>;
}

/** Whether an `x-credentials-optional-if` condition holds for these settings. */
function conditionHolds(condition: Schema | undefined, values: Record<string, unknown>): boolean {
    if (!condition) return false;
    if (condition.anyOf) return (condition.anyOf as Schema[]).some((sub) => conditionHolds(sub, values));
    const value = String(values[condition.field] ?? '').toLowerCase();
    let passes = false;
    if (condition.containsAny) passes = (condition.containsAny as string[]).some((s: string) => value.includes(s.toLowerCase()));
    else if (condition.containsAll) passes = (condition.containsAll as string[]).every((s: string) => value.includes(s.toLowerCase()));
    else if (condition.contains) passes = value.includes(String(condition.contains).toLowerCase());
    else return false;
    if (!passes) return false;
    if (condition.notContains) return !value.includes(String(condition.notContains).toLowerCase());
    return true;
}

/** Whether the step's operation runs with no account (its schema's `x-credentials-optional`, or an
 *  `x-credentials-optional-if` its settings meet): a step type's schema says so for each operation. */
export function operationRunsWithoutAccount(schema: Schema | null | undefined, step: StepSettings | undefined): boolean {
    const config = step?.config;
    const operation = step?.operation;
    if (!schema || !config || !operation) return false;
    // The operation's own definition among the config's members.
    const oneOf = schema.properties?.config?.oneOf as Array<{ $ref?: string }> | undefined;
    const defs = schema.$defs as Record<string, Schema> | undefined;
    if (!oneOf || !defs) return false;
    for (const entry of oneOf) {
        // $ref format: "#/$defs/ClassName"
        const def = entry.$ref ? defs[entry.$ref.split('/').pop() ?? ''] : undefined;
        if (!def?.properties?.operation) continue;
        if (def.properties.operation.const === operation || def.properties.operation.default === operation) {
            return def['x-credentials-optional'] === true || conditionHolds(def['x-credentials-optional-if'], config);
        }
    }
    return false;
}

/** A tool step (`agent_tool_operations` set) whose every allowed operation runs with no account. Entries may be a
 *  string (unscoped) or `{operation, field_scopes}` (resource-scoped). */
export function toolOperationsRunWithoutAccount(schema: Schema | null | undefined, step: StepSettings | undefined): boolean {
    const config = (step?.config ?? {}) as Record<string, unknown>;
    const ops = config.agent_tool_operations;
    if (!Array.isArray(ops) || ops.length === 0) return false;
    return ops.every((op) => {
        const name = typeof op === 'string' ? op : (op as { operation?: string } | null)?.operation;
        return name ? operationRunsWithoutAccount(schema, { operation: name, config }) : false;
    });
}

/** Whether the step can run on NoClick's own key, billed by use, with no account of its own: one operation that runs
 *  with none, or as a tool, every operation it allows. An account attached runs it on that account instead. */
export function runsOnNoClickKey(schema: Schema | null | undefined, step: StepSettings | undefined): boolean {
    const ops = step?.config?.agent_tool_operations;
    if (Array.isArray(ops) && ops.length > 0) return toolOperationsRunWithoutAccount(schema, step);
    return operationRunsWithoutAccount(schema, step);
}
