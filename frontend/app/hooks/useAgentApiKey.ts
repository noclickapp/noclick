// Adding an API key for an agent's provider: how its fields read and the create call. The connect flow for AI accounts
// (AiConnect, in Connections and the agent node's panel alike) draws the fields, so a key validates and fails the same
// way wherever it's added.
import { sendEventAsync } from '~/lib/socket-sender';
import { getAgentCredentialType } from '~/lib/agentCredentialModel';
import { getProviderMetadata, type ModelProvider } from '~/types/provider';

export interface CreatedAgentCredential {
    id: string;
    name: string;
    credential_type: string;
}

/** A human label for an environment variable name. */
export function getFieldLabel(envVar: string): string {
    return envVar
        .replace(/_API_KEY$/, ' API Key')
        .replace(/_API_BASE$/, ' API Base URL')
        .replace(/_API_VERSION$/, ' API Version')
        .replace(/_ACCESS_KEY_ID$/, ' Access Key ID')
        .replace(/_SECRET_ACCESS_KEY$/, ' Secret Access Key')
        .replace(/_REGION_NAME$/, ' Region')
        .replace(/_PROJECT$/, ' Project')
        .replace(/_LOCATION$/, ' Location')
        .replace(/_ACCOUNT_ID$/, ' Account ID')
        .replace(/_TENANT_ID$/, ' Tenant ID')
        .replace(/_JWT$/, ' JWT Token')
        .replace(/_TOKEN$/, ' Token')
        .replace(/^AWS_/, 'AWS ')
        .replace(/^AZURE_/, 'Azure ')
        .replace(/^GOOGLE_/, 'Google ')
        .replace(/^VERTEXAI_/, 'Vertex AI ')
        .replace(/^CLOUDFLARE_/, 'Cloudflare ')
        .replace(/^DATABRICKS_/, 'Databricks ')
        .replace(/^SNOWFLAKE_/, 'Snowflake ')
        .replace(/^PREDIBASE_/, 'Predibase ')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (l) => l.toUpperCase());
}

/** Whether a field holds a secret (a password-style input). */
export function shouldMaskField(envVar: string): boolean {
    const lowerVar = envVar.toLowerCase();
    return lowerVar.includes('key') || lowerVar.includes('secret') || lowerVar.includes('token') || lowerVar.includes('password') || lowerVar.includes('jwt');
}

/** Placeholder text for a field. */
export function getPlaceholder(envVar: string): string {
    if (envVar.includes('_API_BASE') || envVar.includes('_URL')) return 'https://...';
    if (envVar.includes('_API_VERSION')) return 'e.g., 2024-02-01';
    if (envVar.includes('_REGION')) return 'e.g., us-east-1';
    if (envVar.includes('_PROJECT')) return 'e.g., my-project-id';
    if (envVar.includes('_LOCATION')) return 'e.g., us-central1';
    return 'Enter value...';
}

/** Create an agent provider's key credential: `{credentials: {ENV: value}}`, judged by the provider's key probe on the
 *  way in (a refused key comes back as the response's error). */
export async function createAgentKey(provider: ModelProvider, values: Record<string, string>, name?: string) {
    const title = getProviderMetadata(provider)?.title || provider;
    return sendEventAsync({
        event_name: 'credential:create',
        request_id: `create-agent-cred-${Date.now()}`,
        name: name || `${title} - ${new Date().toLocaleDateString()}`,
        credential_type: getAgentCredentialType(provider),
        credential_data: { credentials: values },
        metadata: { provider },
    });
}
