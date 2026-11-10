// Small generated integration facts, shared by schema-free readers. This leaf imports
// JSON only: credentialTypeMap must never acquire an edge back into nodeSchemas.
/** A node whose service shut down (`WorkflowNode.retired`): why, and since when (an ISO date). */
export interface NodeRetirement {
    reason: string;
    since: string;
}

export interface NodeMetaEntry {
    agentToolProvider?: boolean;
    connectionless?: boolean;
    triggerOperations?: string[];
    platformVendorOperations?: string[];
    borrowedCredentialTypes?: string[];
}

export interface PublicOAuthProvider {
    provider: string;
    authorizeUrl: string | null;
    scopeSeparator?: string;
    deviceFlow?: boolean;
    contextFields?: Record<string, { source: "input" | "callback" | "token"; pattern: string | null; choices: string[]; kind: "value" | "host" | "origin"; label: string | null; callbackName: string | null }>;
    scopes: string[];
    pkce: boolean;
    clientIdEnv: string;
    clientSecretEnv: string;
    redirectUriEnv: string;
    authorizeParams: Record<string, string>;
    credentialType: string;
}

export interface IntegrationMetadata {
    oauthProviders?: PublicOAuthProvider[];
    type: string;
    nodeMeta: NodeMetaEntry;
    credentialTypes: Record<string, string>;
    providerLabels: Record<string, string>;
    autoSelectCredential: boolean;
}

/** Adds `additions` into `target`, refusing conflicting declarations rather than depending on glob evaluation order. */
function addDeclarations<T>(target: Record<string, T>, additions: Record<string, T>): void {
    for (const [key, value] of Object.entries(additions)) {
        if (key in target && JSON.stringify(target[key]) !== JSON.stringify(value)) {
            throw new Error(`Conflicting integration declaration: ${key}`);
        }
        target[key] = value;
    }
}

/** `existing` with `additions`, refusing conflicting declarations. */
export function mergeDeclarations<T>(existing: Record<string, T>, additions: Record<string, T>): Record<string, T> {
    const merged = { ...existing };
    addDeclarations(merged, additions);
    return merged;
}

export function collectIntegrationMetadata(files: Record<string, IntegrationMetadata>) {
    // Each integration adds into the same maps: copying them per integration was quadratic, and every page paid it
    // at load (about a second of a throttled laptop's main thread at 1,000 integrations).
    const nodeMeta: Record<string, NodeMetaEntry> = {};
    const credentialTypes: Record<string, string> = {};
    const providerLabels: Record<string, string> = {};
    const autoSelectTypes: string[] = [];
    const oauthProviders: Record<string, PublicOAuthProvider> = Object.create(null);
    for (const [path, meta] of Object.entries(files).sort(([a], [b]) => a.localeCompare(b))) {
        const slug = path.slice(path.lastIndexOf('/') + 1, -'.json'.length);
        if (meta.type !== `automation-${slug}` || meta.type in nodeMeta) {
            throw new Error(`Invalid or duplicate integration metadata: ${path}`);
        }
        nodeMeta[meta.type] = meta.nodeMeta;
        addDeclarations(credentialTypes, meta.credentialTypes);
        addDeclarations(providerLabels, meta.providerLabels);
        for (const spec of meta.oauthProviders ?? []) {
            if (spec.provider in oauthProviders) throw new Error(`Duplicate OAuth provider: ${spec.provider}`);
            if (!Object.values(meta.credentialTypes).includes(spec.credentialType)) throw new Error(`Unknown OAuth credential: ${spec.credentialType}`);
            oauthProviders[spec.provider] = spec;
        }
        if (meta.autoSelectCredential) autoSelectTypes.push(meta.type);
    }
    return { nodeMeta, credentialTypes, providerLabels, autoSelectTypes, oauthProviders };
}

export const INTEGRATION_METADATA = collectIntegrationMetadata(
    import.meta.glob<IntegrationMetadata>('../schemas/nodeMeta/*.json', { eager: true, import: 'default' }),
);
