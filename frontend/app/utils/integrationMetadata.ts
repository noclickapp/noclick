// Small generated integration facts, shared by schema-free readers. This leaf imports
// JSON only: credentialTypeMap must never acquire an edge back into nodeSchemas.
export interface NodeMetaEntry {
    agentToolProvider?: boolean;
    connectionless?: boolean;
    triggerOperations?: string[];
    platformVendorOperations?: string[];
}

export interface PublicOAuthProvider {
    provider: string;
    authorizeUrl: string;
    scopes: string[];
    pkce: boolean;
    clientIdEnv: string;
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

/** Refuse conflicting declarations rather than depending on glob evaluation order. */
export function mergeDeclarations<T>(existing: Record<string, T>, additions: Record<string, T>): Record<string, T> {
    const merged = { ...existing };
    for (const [key, value] of Object.entries(additions)) {
        if (key in merged && JSON.stringify(merged[key]) !== JSON.stringify(value)) {
            throw new Error(`Conflicting integration declaration: ${key}`);
        }
        merged[key] = value;
    }
    return merged;
}

export function collectIntegrationMetadata(files: Record<string, IntegrationMetadata>) {
    let nodeMeta: Record<string, NodeMetaEntry> = {};
    let credentialTypes: Record<string, string> = {};
    let providerLabels: Record<string, string> = {};
    const autoSelectTypes: string[] = [];
    const oauthProviders: Record<string, PublicOAuthProvider> = {};
    for (const [path, meta] of Object.entries(files).sort(([a], [b]) => a.localeCompare(b))) {
        const slug = path.slice(path.lastIndexOf('/') + 1, -'.json'.length);
        if (meta.type !== `automation-${slug}` || meta.type in nodeMeta) {
            throw new Error(`Invalid or duplicate integration metadata: ${path}`);
        }
        nodeMeta = mergeDeclarations(nodeMeta, { [meta.type]: meta.nodeMeta });
        credentialTypes = mergeDeclarations(credentialTypes, meta.credentialTypes);
        providerLabels = mergeDeclarations(providerLabels, meta.providerLabels);
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
