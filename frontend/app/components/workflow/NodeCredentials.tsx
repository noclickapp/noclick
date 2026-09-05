// NodeCredentials component displays required credentials for a workflow node
// and allows users to select which credentials to use from their saved credentials.
// Supports custom credential forms for nodes with special requirements (e.g., agent nodes).

import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';
import { Key, Plus, AlertCircle, X, Check, Edit2, Trash2, ChevronDown, CheckCircle2, Search, ExternalLink, Share2 } from 'lucide-react';
import { SiGoogle } from 'react-icons/si';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { getProviderConfig } from '~/utils/oauthProviders';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { CredentialRequestActions } from './CredentialRequestActions';
import { CredentialFieldInput, type CredentialField } from '~/components/credential/CredentialFieldInput';
import { OAuthConnectForm } from '~/components/credential/OAuthConnectForm';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { CredentialCreateEntryButton } from '~/components/credential/CredentialCreateEntryButton';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { getAgentConfigRecord, getAgentSelectedModel, isPrimaryAgentCredentialKey } from '~/lib/agentCredentialModel';
import { isCliAgentModel } from '~/lib/agentChat';
import { useCredentialOAuth, type Credential } from '~/hooks/useCredentialOAuth';
// Lazy: the agent credential form pulls useModels (~159KB gz) which otherwise
// evaluated eagerly on the dashboard via the always-mounted credential dialog.
// It only renders when configuring an agent (LLM) credential.
const AgentCredentialsForm = lazy(() =>
    import('./AgentCredentialsForm').then((m) => ({ default: m.AgentCredentialsForm }))
);
import { OAuthCredentialForm } from './OAuthCredentialForm';
import { WhatsAppQRCredentialForm } from './WhatsAppQRCredentialForm';
import { MCPCredentialForm } from './MCPCredentialForm';
import { invalidateCredentialsCache, removeCredentialsFromCache, isInjectedDisplayCredential, isConnectionDropped, type CredentialDisplayMeta } from '~/utils/credentialAutoSelect';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchema } from '~/utils/credentialTypes';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { PLAN_LIMITS } from '~/lib/pricing';
import { useOrgContext } from '~/hooks/useOrgContext';
import { isLocalEdition } from '~/lib/edition';
import { useSnapshot } from 'valtio';
import { instanceKeysStore, platformKeyFunds, platformKeyMarker, type PlatformKeyMarker } from '~/lib/instanceKeys';
import { providerKeyLabel } from '~/lib/providerKeys';
import { InstanceKeyPrompt } from '~/components/credential/InstanceKeyPrompt';
import { InstanceSmtpForm } from '~/components/credential/InstanceSmtpForm';

/**
 * Standard interface for custom credential form components.
 * Custom forms handle all their own logic internally (state, fetching, etc.)
 * and call onCredentialIdsChange when the user selects/creates credentials.
 */
export interface CustomCredentialFormProps {
    /** Node data shaped by CredentialsTabContent as `{ operation, config }`.
     * Config fields are nested under `config` — reading them flat (e.g.
     * `nodeData.server_url`) is a bug; use `nodeData.config?.server_url`. */
    nodeData: { operation?: string; config?: Record<string, unknown> };
    /** Current credential ID mappings (credential_type -> credential_id) */
    credentialIds: Record<string, string>;
    /** Callback when credential selection changes */
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    /** Compact hosts (ask drawer, onboarding) hide the ask-someone-else actions,
        matching what NodeCredentials already does for its own copy of them. */
    compact?: boolean;
}

/**
 * Wrapper for MCPCredentialForm to adapt CustomCredentialFormProps interface.
 * Extracts server_url from nodeData for OAuth discovery.
 */
const MCPCredentialFormWrapper = ({ nodeData, credentialIds, onCredentialIdsChange }: CustomCredentialFormProps) => {
    const serverUrl = nodeData?.config?.server_url as string | undefined;

    return (
        <MCPCredentialForm
            serverUrl={serverUrl}
            credentialIds={credentialIds}
            onCredentialIdsChange={onCredentialIdsChange}
        />
    );
};

/**
 * Registry of custom credential form components by node type.
 * Nodes listed here will use their custom form instead of the default credential UI.
 * Custom forms must implement CustomCredentialFormProps interface.
 */
const CUSTOM_CREDENTIAL_FORMS: Record<
    string,
    ComponentType<CustomCredentialFormProps> | LazyExoticComponent<ComponentType<CustomCredentialFormProps>>
> = {
    'agent': AgentCredentialsForm,
    'mcp-server': MCPCredentialFormWrapper,
    // Future custom forms can be added here:
    // 'some-other-node': SomeOtherCredentialsForm,
};

/**
 * Whether a node type's credentials are created through a custom form whose
 * inputs depend on node-specific config (agent → selected model, mcp-server →
 * server URL). Such credentials can't be created standalone outside a node, so
 * the create-credential dialog excludes these node types from its service list.
 */
export function hasCustomCredentialForm(nodeType: string): boolean {
    return nodeType in CUSTOM_CREDENTIAL_FORMS;
}

// Node types where credentials are truly optional (can function without any credentials)
// Most nodes with anyOf null in schema still require credentials to work - the null is for initial state
// Only add nodes here that can genuinely operate without any credentials
const TRULY_OPTIONAL_CREDENTIALS: Set<string> = new Set([
    'automation-rss',           // Can parse public RSS feeds without authentication
    'automation-http-request',  // Can make requests to public endpoints without auth
    'mcp-server',               // auth_type defaults to 'none'; hosting mode needs no credentials
]);

/**
 * Extract the provider from an agent model ID.
 * Model ID formats:
 * - OpenRouter: "openrouter/{provider}/{model}" (e.g., "openrouter/openai/gpt-4o-mini")
 * - Direct provider: "{provider}/{model}" (e.g., "azure/gpt-4", "bedrock/claude-3")
 * - Unprefixed: just "{model}" (rare, check patterns)
 */
export function getProviderFromModelId(modelId: string): string | null {
    if (!modelId) return null;

    // OpenRouter models are prefixed with "openrouter/"
    if (modelId.startsWith('openrouter/')) {
        return 'openrouter';
    }

    // Check if the model has a provider prefix (e.g., "azure/gpt-4", "bedrock/claude-3")
    // The first segment is the provider
    const segments = modelId.split('/');
    if (segments.length >= 2) {
        const firstSegment = segments[0];
        // If it has a prefix, that's the provider - return it directly
        // Don't try to infer from model name patterns when there's an explicit provider
        return firstSegment;
    }

    // For unprefixed models (no slash), try to infer from model name patterns
    // This handles edge cases like just "gpt-4" or "claude-3" without provider prefix
    const lowerModel = modelId.toLowerCase();
    if (lowerModel.includes('gpt-') || lowerModel.includes('o1-') || lowerModel.includes('o3-')) {
        return 'openai';
    }
    if (lowerModel.includes('claude')) {
        return 'anthropic';
    }
    if (lowerModel.includes('gemini')) {
        return 'gemini';
    }

    return null;
}

/**
 * Check if an agent node requires credentials.
 *
 * Pure — no models database — so it can only decide the cases string inspection
 * settles unambiguously. A CLI harness is exactly that: `agentAllowsUsageBased`
 * exempts every one of them from platform billing on identity alone, no provider
 * inference needed, so a harness with no primary credential is definitively
 * missing one. LLM-path models still defer to `useAgentCredentialsRequired`,
 * which resolves the provider against the catalog; guessing here from model-name
 * patterns produced false positives, which is why this used to answer a blanket
 * false and left CLI agents invisible to canvas validation entirely.
 *
 * `agent_env` deliberately does NOT count — it carries sandbox env vars, never
 * auth (see isPrimaryAgentCredentialKey).
 */
function agentRequiresCredentials(nodeData: Record<string, any>, credentialIds: Record<string, string>): boolean {
    const hasPrimaryCredential = Object.entries(credentialIds).some(
        ([key, id]) => isPrimaryAgentCredentialKey(key) && id && id.trim() !== ''
    );
    if (hasPrimaryCredential) return false;

    return isCliAgentModel(getAgentSelectedModel(undefined, getAgentConfigRecord(nodeData)));
}

/**
 * Check if the currently selected operation has x-credentials-optional in its schema.
 * This allows any node to mark specific operations as not requiring credentials
 * without needing hardcoded lists in this component.
 */
function isOperationCredentialsOptional(nodeType: string, nodeData?: Record<string, any>): boolean {
    if (!nodeData) return false;

    const schema = NODE_SCHEMAS[nodeType];
    if (!schema) return false;

    const config = nodeData.config as Record<string, unknown> | undefined;
    const operation = nodeData.operation as string | undefined;
    if (!config || !operation) return false;

    const evaluateCondition = (condition: any, values: Record<string, unknown>): boolean => {
        if (!condition) return false;
        if (condition.anyOf) {
            return (condition.anyOf as any[]).some(sub => evaluateCondition(sub, values));
        }
        const condVal = String(values[condition.field] ?? '').toLowerCase();
        let passes = false;
        if (condition.containsAny) {
            passes = (condition.containsAny as string[]).some((s: string) => condVal.includes(s.toLowerCase()));
        } else if (condition.containsAll) {
            passes = (condition.containsAll as string[]).every((s: string) => condVal.includes(s.toLowerCase()));
        } else if (condition.contains) {
            passes = condVal.includes(String(condition.contains).toLowerCase());
        } else {
            return false;
        }
        if (!passes) return false;
        if (condition.notContains) {
            return !condVal.includes(String(condition.notContains).toLowerCase());
        }
        return true;
    };

    // Look up the operation's schema definition in the config oneOf
    const configProp = schema.properties?.config;
    const oneOf = configProp?.oneOf as Array<{ $ref?: string }> | undefined;
    const defs = (schema as any).$defs as Record<string, any> | undefined;
    if (!oneOf || !defs) return false;

    // Find the definition that matches this operation
    for (const entry of oneOf) {
        if (!entry.$ref) continue;
        // $ref format: "#/$defs/ClassName"
        const defName = entry.$ref.split('/').pop();
        if (!defName) continue;
        const def = defs[defName];
        if (!def?.properties?.operation) continue;
        // Match by operation const value
        if (def.properties.operation.const === operation || def.properties.operation.default === operation) {
            const optional = def['x-credentials-optional'] === true || evaluateCondition(def['x-credentials-optional-if'], config);
            // Optional in the cloud because NoClick's key pays; on a self-hosted
            // instance only while the operator configured that key.
            return optional && platformKeyFunds(platformKeyMarker(def));
        }
    }

    return false;
}

/** The platform key the selected operation runs on, if it declares one. */
export function operationPlatformKey(nodeType: string, nodeData?: Record<string, any>): PlatformKeyMarker | null {
    const operation = nodeData?.operation as string | undefined;
    const schema = NODE_SCHEMAS[nodeType];
    const oneOf = schema?.properties?.config?.oneOf as Array<{ $ref?: string }> | undefined;
    const defs = (schema as any)?.$defs as Record<string, any> | undefined;
    if (!operation || !oneOf || !defs) return null;
    for (const entry of oneOf) {
        const def = defs[entry.$ref?.split('/').pop() ?? ''];
        const op = def?.properties?.operation;
        if (op && (op.const === operation || op.default === operation)) return platformKeyMarker(def);
    }
    return null;
}

/**
 * Tool-provider mode check: a non-empty operation allowlist where EVERY
 * allowlisted operation is x-credentials-optional. Entries may be either a
 * string (unscoped) or {operation, field_scopes} (resource-scoped).
 */
function providerAllowlistAllOptional(nodeType: string, nodeData?: Record<string, unknown>): boolean {
    const config = (nodeData?.config ?? {}) as Record<string, unknown>;
    const ops = config.agent_tool_operations;
    if (!Array.isArray(ops) || ops.length === 0) return false;
    return ops.every(op => {
        const opName = typeof op === 'string' ? op : op?.operation;
        return opName ? isOperationCredentialsOptional(nodeType, { operation: opName, config }) : false;
    });
}

/**
 * Credential check for PROVIDER-wired nodes (agent/MCP tool providers): the
 * node exposes an operation allowlist instead of running one operation, so
 * credentials are required only if some allowlisted operation needs them —
 * e.g. reddit's get_subreddit_posts is x-credentials-optional, so a reddit
 * provider exposing only that action needs no credentials.
 */
export function providerCredentialsMissing(
    nodeType: string,
    credentialIds: Record<string, string> = {},
    nodeData?: Record<string, unknown>
): boolean {
    if (providerAllowlistAllOptional(nodeType, nodeData)) return false;
    // Mixed/required allowlist: strip `operation` so the single-op optional
    // check can't apply — a lingering operation from before provider wiring
    // (e.g. exa's default 'search') would wave the whole allowlist through.
    return hasUnconnectedCredentials(nodeType, credentialIds, { ...nodeData, operation: undefined });
}

/**
 * Usage-based billing applies when the node can run on NoClick's platform key:
 * single-op mode → the selected operation is credentials-optional; tool-provider
 * mode (agent_tool_operations set) → every allowlisted operation is. BYOK stays
 * available either way — an attached credential switches billing to the user's key.
 */
export function isUsageBasedBillingAvailable(nodeType: string, nodeData?: Record<string, any>): boolean {
    if (isLocalEdition()) return false; // hosted platform key only
    const ops = (nodeData?.config as Record<string, unknown> | undefined)?.agent_tool_operations;
    if (Array.isArray(ops) && ops.length > 0) return providerAllowlistAllOptional(nodeType, nodeData);
    return isOperationCredentialsOptional(nodeType, nodeData);
}

// Helper function to check if a node type requires credentials that aren't connected
// Returns true if credentials are REQUIRED but not connected
// Returns false if credentials are optional or if credentials are connected
export function hasUnconnectedCredentials(
    nodeType: string,
    credentialIds: Record<string, string> = {},
    nodeData?: Record<string, any>
): boolean {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema?.properties?.credentials) return false;

    // Check if credentials are explicitly null (no credentials needed at all)
    // This can be either `{ type: 'null' }` or `{ anyOf: [{ type: 'null' }] }` (Pydantic pattern)
    const credSchema = schema.properties.credentials;
    if (credSchema.type === 'null') return false;
    if (credSchema.anyOf?.length === 1 && credSchema.anyOf[0].type === 'null') return false;

    // Special handling for agent nodes - depends on selected model
    if (nodeType === 'agent') {
        return agentRequiresCredentials(nodeData || {}, credentialIds);
    }

    // Check if the current operation marks credentials as optional via schema extension.
    // Any node can add "x-credentials-optional": true to an operation's model_config
    // to indicate it can run without credentials (e.g., public RSS feeds).
    if (isOperationCredentialsOptional(nodeType, nodeData)) {
        return false;
    }

    // Some nodes have truly optional credentials (can work without any)
    // Note: Many schemas have anyOf with null + default:null pattern, but this is for
    // initial state - the node still requires credentials to function. Only nodes in
    // TRULY_OPTIONAL_CREDENTIALS can genuinely operate without credentials.
    if (TRULY_OPTIONAL_CREDENTIALS.has(nodeType)) return false;

    // Check if any credential is selected
    const hasAnyCredential = Object.values(credentialIds).some(id => id && id.trim() !== '');

    // Credentials are required but none selected
    return !hasAnyCredential;
}

// Credential-UI detection routed through the single kind discriminator, so the
// in-app UI and the public provide page classify credential types identically.
// Edit/Share/Delete are owner-only (the backend rejects them from anyone else).
// Gate on the backend's ownership signals, NOT on `owner_name` — that label is
// only set on injected run-as-owner descriptors, so a credential shared with the
// viewer directly has none and would wrongly show dead-end controls.
const isOwnedByViewer = (cred: Credential): boolean =>
    cred.access_type === 'owner' || cred.owned_by_me === true;

const ownerLabel = (cred: Credential): string =>
    cred.owner_name || cred.shared_by_name || cred.shared_by_email || 'another user';

const isOAuthCredential = (credentialSchema: any): boolean =>
    kindFromCredentialType(credentialSchema?.['x-credential-type']) === 'oauth';

const isQRScanCredential = (credentialSchema: any): boolean =>
    kindFromCredentialType(credentialSchema?.['x-credential-type']) === 'qr_scan';

const getOAuthProvider = (credentialSchema: any): string | undefined => {
    return credentialSchema?.['x-oauth-provider'];
};

const getOAuthScopes = (credentialSchema: any): string[] => {
    return credentialSchema?.['x-oauth-scopes'] || [];
};

const getOAuthUserScopes = (credentialSchema: any): string[] => {
    return credentialSchema?.['x-oauth-user-scopes'] || [];
};

// Get credential URL where users can obtain their API key/token
const getCredentialUrl = (credentialSchema: any): string | undefined => {
    return credentialSchema?.['x-credential-url'];
};

// Warning notice shown above a credential (e.g. integration pending approval / unavailable)
const getCredentialNotice = (credentialSchema: any): string | undefined => {
    return credentialSchema?.['x-credential-notice'];
};

// Helper to extract field info from JSON Schema
const getFieldsFromSchema = (credentialSchema: any): CredentialField[] => {
    if (!credentialSchema?.properties) return [];

    const required = credentialSchema.required || [];
    return Object.entries(credentialSchema.properties)
        .filter(([_name, prop]: [string, any]) => !prop['ui:hidden'])
        .map(([name, prop]: [string, any]) => {
            const enumValues: string[] | undefined = prop.enum;
            const enumNames: string[] | undefined = prop.enumNames;
            return {
                name,
                label: prop.title || name,
                type: prop['ui:widget'] === 'password' ? 'password' : 'text',
                placeholder: prop['ui:placeholder'] || prop.placeholder,
                required: required.includes(name),
                description: prop.description,
                default: prop.default,
                options: Array.isArray(enumValues)
                    ? enumValues.map((v, i) => ({ value: v, label: enumNames?.[i] ?? v }))
                    : undefined,
            };
        });
};

interface CredentialRequirement {
    credential_type: string;
    label: string;
    description: string;
    schema?: any;  // JSON Schema defining credential structure
}

/** Dead-but-recoverable: the provider session dropped (reconnecting the same
 *  credential fixes it), as opposed to revoked_at which is a terminal disconnect. */
const isDisconnected = (cred: Credential) => isConnectionDropped(cred);

/** Sort helper: healthy first, then disconnected, then revoked. */
const deadRank = (cred: Credential) => (cred.revoked_at ? 2 : isDisconnected(cred) ? 1 : 0);

interface NodeCredentialsProps {
    nodeType: string;
    nodeData?: Record<string, any>;  // Full node data (needed for agent nodes to get selected model)
    credentialIds?: Record<string, string>;  // Maps credential_type -> credential_id
    // credentialMeta carries display-only descriptors (id/name/type, NO secret) for
    // the just-selected credential(s) so collaborators resolve the name instantly.
    // credentialRemoved carries credential id(s) just deleted, so collaborators drop
    // them from their dropdowns live.
    onChange?: (credentialIds: Record<string, string>, credentialMeta?: Record<string, CredentialDisplayMeta>, credentialRemoved?: string[]) => void;
    credentialVariables?: { name: string; label: string; credentialTypes: string[] }[];  // Credential variables with type metadata from set-variable nodes
    /** Compact mode: hides credential type title/description and share request option. Used in builder input drawer. */
    compact?: boolean;
}

export const NodeCredentials = ({ nodeType, nodeData = {}, credentialIds = {}, onChange, credentialVariables, compact }: NodeCredentialsProps) => {
    const [schema, setSchema] = useState<any>(null);
    const [requiredCredentials, setRequiredCredentials] = useState<CredentialRequirement[]>([]);

    const isCredentialSchemaVisible = useCallback(
        (credSchema: any): boolean => !credSchema?.['x-credential-hidden'],
        []
    );

    const usageBasedBillingAvailable = useMemo(
        () => isUsageBasedBillingAvailable(nodeType, nodeData),
        [nodeType, nodeData]
    );
    // Self-hosted: a platform-keyed operation runs on the INSTANCE's key. The
    // store flips this the moment a key is saved anywhere.
    const instanceKeys = useSnapshot(instanceKeysStore);
    const selfHosted = isLocalEdition();
    const platformKey = useMemo(() => (selfHosted ? operationPlatformKey(nodeType, nodeData) : null), [selfHosted, nodeType, nodeData]);
    const instanceKeyConfigured = !!platformKey && instanceKeys.configured.includes(platformKey.env);
    const outboundEmailConfigured =
        instanceKeys.configured.includes('FROM_EMAIL') &&
        (instanceKeys.configured.includes('SMTP_HOST') || instanceKeys.configured.includes('RESEND_API_KEY'));

    // Check if this node type has a custom credential form
    const CustomCredentialForm = CUSTOM_CREDENTIAL_FORMS[nodeType];

    // Stable callback for credential ID changes (used by custom forms)
    const handleCredentialIdsChange = useCallback((newCredentialIds: Record<string, string>) => {
        onChange?.(newCredentialIds);
    }, [onChange]);

    // Handle credential selection - needs to be defined before useCredentialOAuth
    const handleCredentialSelect = useCallback((credentialType: string, credentialId: string, knownCredential?: { id: string; name: string; credential_type: string }) => {
        // Only keep keys that are valid current credential types — this removes stale keys
        // from old schema versions (e.g. "supabaseoauthcredential" vs "supabase_oauth") that
        // would otherwise shadow the correct new entry in the credentialIds map.
        const validTypes = new Set(requiredCredentialsRef.current.map(r => r.credential_type));
        const cleaned: Record<string, string> = {};
        for (const [k, v] of Object.entries(credentialIds)) {
            if (validTypes.has(k)) {
                cleaned[k] = v;
            }
        }
        // Carry a display-only descriptor for the just-selected credential so
        // collaborators resolve its name instantly over the node:update sync (no
        // secret material — id/name/type only). Resolve from the loaded list, else
        // from an explicitly-passed credential (e.g. one just created, before the
        // list refresh has re-rendered) so the name still travels in that case.
        const resolved = availableCredentialsRef.current.find(c => c.id === credentialId) || knownCredential;
        const credentialMeta: Record<string, CredentialDisplayMeta> | undefined =
            resolved && resolved.id === credentialId
                ? { [credentialId]: { id: resolved.id, name: resolved.name, credential_type: resolved.credential_type } }
                : undefined;
        onChange?.({ ...cleaned, [credentialType]: credentialId }, credentialMeta);
    }, [credentialIds, onChange]);

    // Ref to track required credentials for OAuth callback
    const requiredCredentialsRef = useRef<CredentialRequirement[]>([]);
    useEffect(() => {
        requiredCredentialsRef.current = requiredCredentials;
    }, [requiredCredentials]);

    // Ref to the resolved credential list so handleCredentialSelect (defined before
    // useCredentialOAuth) can build a display descriptor for the selected credential.
    const availableCredentialsRef = useRef<Credential[]>([]);

    // Use shared OAuth hook - handles all OAuth providers and credential loading
    const {
        availableCredentials,
        loading,
        loadCredentials,
        connect: oauthConnect,
        connectOrgConsent,
        isConnecting: oauthIsConnecting,
        connectingProvider,
        error: oauthError,
        planLimitError: oauthPlanLimitError,
        credentialTier,
        clearError: clearOAuthError,
        pendingSelection,
        resolvePendingSelection,
        cancelConnect: cancelOAuthConnect,
    } = useCredentialOAuth({
        onCredentialCreated: async (credentialId, provider, credential) => {
            // Find the matching credential requirement by provider
            const matchingReq = requiredCredentialsRef.current.find(
                req => isOAuthCredential(req.schema) && getOAuthProvider(req.schema) === provider
            );
            if (matchingReq) {
                handleCredentialSelect(matchingReq.credential_type, credentialId, credential);
                // Validate API access if the credential schema requires it
                if (matchingReq.schema?.['x-oauth-validates-api-access']) {
                    try {
                        const result = await sendEventAsync<{
                            valid?: boolean;
                            error?: string;
                            help_url?: string;
                        }>({
                            event_name: 'credential:validate_access',
                            credential_id: credentialId,
                            node_type: nodeType,
                        });
                        if (result && !result.valid) {
                            setValidationError({
                                message: result.error || 'API access validation failed.',
                                helpUrl: result.help_url,
                            });
                        }
                    } catch {
                        // silently ignore validation failures — don't block credential selection
                    }
                }
            }
        },
    });

    // Keep the ref current so handleCredentialSelect can build a display descriptor.
    availableCredentialsRef.current = availableCredentials;

    // Note: an owner's credential set on a node is resolved as the workflow owner
    // at execution and is NOT shared into a collaborator's account, so it won't be
    // in their credential:list. Its display info (name + owner tag) is fetched
    // workflow-scoped by FlowCanvas (credential:display_info) and merged into the
    // cache → availableCredentials, so the dropdown resolves it here. No list-refetch
    // backoff is needed (there is no per-user share to wait for).

    const [error, setError] = useState<string | null>(null);
    const [creatingCredentialType, setCreatingCredentialType] = useState<string | null>(null);
    // Create-form state lives inside CredentialCreatePanel; createError remains
    // for OAuth-section errors surfaced outside the panel.
    const [createError, setCreateError] = useState<string | null>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    // Post-connect API access validation error (e.g. GBP API not approved yet).
    const [validationError, setValidationError] = useState<{ message: string; helpUrl?: string } | null>(null);
    const [orgContext] = useOrgContext();
    const isOrgMember = orgContext.id && orgContext.role === 'member';

    // Edit state
    const [editingCredentialId, setEditingCredentialId] = useState<string | null>(null);
    const [editCredentialName, setEditCredentialName] = useState('');
    const [editCredentialFormData, setEditCredentialFormData] = useState<Record<string, string>>({});
    const [editLoading, setEditLoading] = useState(false);
    const [editError, setEditError] = useState<string | null>(null);


    // Dropdown state
    const [openDropdownType, setOpenDropdownType] = useState<string | null>(null);
    const [credentialSearchQuery, setCredentialSearchQuery] = useState('');
    const dropdownRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    // Delete confirmation dialog state
    const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
    const [credentialToDelete, setCredentialToDelete] = useState<{ id: string; name: string; type: string } | null>(null);

    // Share dialog state
    const [shareCredential, setShareCredential] = useState<{ id: string; name: string } | null>(null);

    const getCredentialCap = useCallback(() => {
        return PLAN_LIMITS[credentialTier as keyof typeof PLAN_LIMITS]?.credentials_per_type ?? Infinity;
    }, [credentialTier]);

    const getVisibleCredentialCount = useCallback((credentialType: string) => {
        // Exclude injected run-as-owner display descriptors (never the viewer's own)
        // so they don't inflate the viewer's plan-limit cap count — matches the
        // backend, which counts only the viewer's own + shared creds. Keying on the
        // display-only registry (not owner_name) also excludes a live descriptor that
        // hasn't been owner-enriched yet.
        return availableCredentials.filter(c => c.credential_type === credentialType && !c.over_cap && !isInjectedDisplayCredential(c.id)).length;
    }, [availableCredentials]);

    const showCredentialLimitPopup = useCallback((cap: number) => {
        setPlanLimitError(
            `Plan limit reached: ${credentialTier.charAt(0).toUpperCase() + credentialTier.slice(1)} plan allows up to ${cap} credentials per node type (including shared). Ask an instance administrator to adjust this limit.`
        );
    }, [credentialTier]);

    const canCreateCredential = useCallback((credentialType: string) => {
        const cap = getCredentialCap();
        if (getVisibleCredentialCount(credentialType) < cap) return true;
        if ((credentialTier === 'free' || credentialTier === 'plus') && !isOrgMember) {
            showCredentialLimitPopup(cap);
            return false;
        }
        return true;
    }, [credentialTier, getCredentialCap, getVisibleCredentialCount, isOrgMember, showCredentialLimitPopup]);

    // Load schema for this node type (synchronous - from imported JSON schemas)
    useEffect(() => {
        try {
            setError(null);

            // Get schema from imported schemas
            const schemaData = NODE_SCHEMAS[nodeType];

            if (!schemaData) {
                throw new Error(`No schema found for node type: ${nodeType}`);
            }

            setSchema(schemaData);

            // Extract credentials schema from root schema
            // Root schema now has structure: { properties: { config: {...}, credentials: {...} } }
            const credentialProp = schemaData.properties?.credentials;

            if (!credentialProp || credentialProp.type === 'null') {
                // No credentials required for this node type
                setRequiredCredentials([]);
                return;
            }

            // Resolve $ref if present
            const resolveRef = (ref: string) => {
                const path = ref.replace('#/$defs/', '');
                return schemaData.$defs?.[path] || schemaData.definitions?.[path];
            };

            // Helper to create credential requirement from schema. The label is
            // humanized ONCE here ('GoogleSheetsOAuth' → 'Google Sheets OAuth')
            // so every downstream use — headings, 'Connect new X', default
            // credential names — reads naturally.
            const createCredentialRequirement = (credSchema: any): CredentialRequirement => {
                const credentialType = getCredentialTypeFromSchema(credSchema);
                const rawLabel = credSchema.title?.replace('Credential', '') || 'Credential';
                return {
                    credential_type: credentialType,
                    label: humanizeCredentialLabel(rawLabel),
                    description: credSchema.description || '',
                    schema: credSchema
                };
            };

            // Handle different schema structures:
            // 1. Direct $ref: { "$ref": "#/$defs/CredentialType" }
            // 2. anyOf with $ref: { "anyOf": [{ "$ref": "..." }, { "type": "null" }] }
            // 3. anyOf with multiple $refs: Union types like AirtablePATCredential | AirtableOAuthCredential
            const credentials: CredentialRequirement[] = [];

            if (credentialProp.$ref) {
                // Direct $ref - single credential type
                const credentialSchema = resolveRef(credentialProp.$ref);
                if (credentialSchema) {
                    credentials.push(createCredentialRequirement(credentialSchema));
                }
            } else if (credentialProp.anyOf) {
                // anyOf pattern - find ALL non-null types with $ref (supports Union types)
                const refEntries = credentialProp.anyOf.filter((entry: any) => entry.$ref);
                for (const refEntry of refEntries) {
                    const credentialSchema = resolveRef(refEntry.$ref);
                    if (credentialSchema && isCredentialSchemaVisible(credentialSchema)) {
                        credentials.push(createCredentialRequirement(credentialSchema));
                    }
                }
            } else {
                // Direct schema (no $ref)
                credentials.push(createCredentialRequirement(credentialProp));
            }

            if (credentials.length === 0) {
                setRequiredCredentials([]);
                return;
            }

            // Sort credentials: OAuth first, then API Key, then PAT, then others
            // This provides the best UX as OAuth is typically easiest for users.
            // Exception: OAuth that REQUIRES a bring-your-own app (no NoClick global
            // app) is harder than a token, so it sorts last (x-oauth-requires-custom-client).
            const credentialPriority = (cred: CredentialRequirement): number => {
                if (isOAuthCredential(cred.schema)) {
                    return cred.schema?.['x-oauth-requires-custom-client'] ? 4 : 0;
                }
                const type = cred.credential_type.toLowerCase();
                if (type.includes('api_key') || type.includes('apikey')) return 1; // API Key second
                if (type.includes('pat') || type.includes('personal_access_token')) return 2; // PAT third
                return 3; // Others last
            };
            credentials.sort((a, b) => credentialPriority(a) - credentialPriority(b));

            setRequiredCredentials(credentials);
        } catch (err) {
            console.error('[NodeCredentials] Error loading schema:', err);
            setError(err instanceof Error ? err.message : 'Failed to load schema');
        }
    }, [nodeType, isCredentialSchemaVisible]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setOpenDropdownType(null);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, []);

    // Focus search input when dropdown opens
    useEffect(() => {
        if (openDropdownType && searchInputRef.current) {
            searchInputRef.current.focus();
        }
    }, [openDropdownType]);

    // Clear search when dropdown closes
    useEffect(() => {
        if (!openDropdownType) {
            setCredentialSearchQuery('');
        }
    }, [openDropdownType]);

    // In compact ask drawers, pre-select the newest existing credential so the
    // user can confirm instead of noticing and opening a subtle picker.
    //
    // `onChange` is controlled: we emit a selection and wait for the parent to
    // echo it back through `credentialIds`. Callers commonly pass a fresh inline
    // `onChange`/`credentialIds` each render, so this effect re-runs constantly —
    // and until the echo lands, `credentialIds` still looks empty. Without a
    // guard that re-emits the same auto-selection every render, spamming the
    // parent's onChange (TriggerTestsView's persist→refetch loop hit ~520
    // redundant set_credential calls this way, 2026-06-16). The ref records the
    // types we've already auto-selected so each is emitted at most once.
    const autoSelectedTypesRef = useRef<Set<string>>(new Set());
    useEffect(() => {
        if (!compact || requiredCredentials.length === 0 || availableCredentials.length === 0) return;

        const nextCredentialIds = { ...credentialIds };
        let changed = false;

        for (const req of requiredCredentials) {
            if (nextCredentialIds[req.credential_type]?.trim()) continue;
            if (autoSelectedTypesRef.current.has(req.credential_type)) continue;
            const match = availableCredentials.find(
                c => c.credential_type === req.credential_type && !c.over_cap
            );
            if (!match) continue;
            nextCredentialIds[req.credential_type] = match.id;
            autoSelectedTypesRef.current.add(req.credential_type);
            changed = true;
        }

        if (changed) {
            onChange?.(nextCredentialIds);
        }
    }, [availableCredentials, compact, credentialIds, onChange, requiredCredentials]);

    // Handle credential creation — the panel owns the form state and shows the
    // returned error; plan-limit errors route to the shared banner instead.
    const handleCreateCredential = useCallback(async (
        req: CredentialRequirement, name: string, data: Record<string, string>,
    ): Promise<string | null> => {
        if (!canCreateCredential(req.credential_type)) return null;
        try {
            const response = await sendEventAsync({
                event_name: 'credential:create',
                request_id: `create-${Date.now()}`,
                name: name || `${req.label} - ${new Date().toLocaleDateString()}`,
                credential_type: req.credential_type,
                credential_data: data,
                metadata: {}
            });

            if (response?.success && response.credential) {
                // Invalidate cache and reload credentials list
                invalidateCredentialsCache();
                await loadCredentials();

                // Auto-select the newly created credential. Pass the created
                // credential so its descriptor travels even though the list refresh
                // above may not have re-rendered into availableCredentials yet.
                handleCredentialSelect(req.credential_type, response.credential.id, response.credential);
                setCreatingCredentialType(null);
                return null;
            }
            const errMsg = response?.error || response?.message || 'Failed to create credential';
            if (isPlanLimitError(errMsg)) {
                setPlanLimitError(errMsg);
                return null;
            }
            return errMsg;
        } catch (err) {
            console.error('[NodeCredentials] Error creating credential:', err);
            const errMsg = err instanceof Error ? err.message : 'Failed to create credential';
            if (isPlanLimitError(errMsg)) {
                setPlanLimitError(errMsg);
                return null;
            }
            return errMsg;
        }
    }, [canCreateCredential, loadCredentials, handleCredentialSelect]);

    const cancelCreate = useCallback(() => {
        setCreatingCredentialType(null);
    }, []);

    // Edit credential handlers
    const startEditCredential = useCallback((credential: Credential, req: CredentialRequirement) => {
        setEditingCredentialId(credential.id);
        setEditCredentialName(credential.name);
        // Initialize form data with empty values (user will need to re-enter for security)
        setEditCredentialFormData({});
        setEditError(null);
    }, []);

    const handleUpdateCredential = useCallback(async (req: CredentialRequirement) => {
        setEditError(null);
        setEditLoading(true);

        try {
            const response = await sendEventAsync({
                event_name: 'credential:update',
                request_id: `update-cred-${Date.now()}`,
                credential_id: editingCredentialId!,
                name: editCredentialName || undefined,
                credential_data: editCredentialFormData
            });

            if (response?.success) {
                // Invalidate cache and reload credentials
                invalidateCredentialsCache();
                await loadCredentials();
                setEditingCredentialId(null);
                setEditCredentialName('');
                setEditCredentialFormData({});
            } else {
                setEditError(response?.message || 'Failed to update credential');
            }
        } catch (err) {
            console.error('[NodeCredentials] Error updating credential:', err);
            setEditError(err instanceof Error ? err.message : 'Failed to update credential');
        } finally {
            setEditLoading(false);
        }
    }, [editingCredentialId, editCredentialName, editCredentialFormData, loadCredentials]);

    const cancelEdit = useCallback(() => {
        setEditingCredentialId(null);
        setEditCredentialName('');
        setEditCredentialFormData({});
        setEditError(null);
    }, []);

    const updateEditField = useCallback((fieldName: string, value: string) => {
        setEditCredentialFormData(prev => ({ ...prev, [fieldName]: value }));
    }, []);

    // Open delete confirmation dialog
    const openDeleteDialog = useCallback((credentialId: string, credentialName: string, credentialType: string) => {
        setCredentialToDelete({ id: credentialId, name: credentialName, type: credentialType });
        setIsDeleteDialogOpen(true);
    }, []);

    // Confirm credential deletion
    const confirmDeleteCredential = useCallback(async () => {
        if (!credentialToDelete) return;

        try {
            const response = await sendEventAsync({
                event_name: 'credential:delete',
                request_id: `delete-cred-${Date.now()}`,
                credential_id: credentialToDelete.id,
                confirm: true,
            });

            if (response?.success) {
                // Invalidate cache and reload credentials
                invalidateCredentialsCache();
                await loadCredentials();
                // Drop it from the shared in-memory cache too (covers optimistic
                // entries that loadCredentials wouldn't otherwise clear).
                removeCredentialsFromCache([credentialToDelete.id]);
                // Broadcast the deletion so collaborators drop it from their
                // dropdowns live (rides the node:update sync, like the add path).
                // Clear the node's selection if it pointed at the deleted credential.
                const newCredentialIds = { ...credentialIds };
                if (newCredentialIds[credentialToDelete.type] === credentialToDelete.id) {
                    delete newCredentialIds[credentialToDelete.type];
                }
                onChange?.(newCredentialIds, undefined, [credentialToDelete.id]);
            } else {
                // The reason rides `error`; `message` is only set on success.
                toast.error(response?.error || 'Failed to delete credential');
            }
        } catch (err) {
            console.error('[NodeCredentials] Error deleting credential:', err);
            toast.error('Failed to delete credential');
        } finally {
            setCredentialToDelete(null);
        }
    }, [credentialToDelete, loadCredentials, credentialIds, onChange]);

    if (loading) {
        return (
            <div className="flex items-center justify-center py-8">
                <div className="text-sm text-muted-foreground dark:text-zinc-500">Loading credentials...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                <div className="flex items-center gap-2 text-sm text-red-500">
                    <AlertCircle className="h-4 w-4" />
                    <span>{error}</span>
                </div>
            </div>
        );
    }

    // Self-hosted Send Email: no credential, but the instance must have somewhere to send from.
    if (selfHosted && nodeType === 'automation-send-email' && !CustomCredentialForm) {
        return outboundEmailConfigured ? (
            <p className="text-xs text-muted-foreground">
                Sends through this instance&apos;s mail server — change it under Settings → Self-hosted.
            </p>
        ) : (
            <div className="max-w-md">
                <InstanceSmtpForm />
            </div>
        );
    }

    // Self-hosted, an operation the node's own credential cannot fund (LinkedIn
    // scraping runs on Apify): ask for the instance's key, not a credential.
    if (platformKey && !platformKey.byok) {
        const label = providerKeyLabel(platformKey.env);
        return instanceKeyConfigured ? (
            <p className="text-xs text-green-600 dark:text-green-400">
                ✓ Runs on this instance&apos;s {label} key — no credential needed
            </p>
        ) : (
            <div className="max-w-md">
                <InstanceKeyPrompt
                    envVar={platformKey.env}
                    title={`Run this on ${label}`}
                    steps={[
                        `Create ${/^[aeiou]/i.test(label) ? 'an' : 'a'} ${label} account and copy its API key (button below).`,
                        `Paste it here. Every operation on this instance that runs on ${label} uses it.`,
                    ]}
                    submitLabel="Save"
                    onSaved={() => undefined}
                />
            </div>
        );
    }

    // If no default credentials required and no custom form, show empty state
    if (requiredCredentials.length === 0 && !CustomCredentialForm) {
        return (
            <div className="flex items-center justify-center py-8">
                <div className="text-center">
                    <Key className="h-8 w-8 text-muted-foreground/70 dark:text-zinc-600 mx-auto mb-2" />
                    <div className="text-sm text-muted-foreground dark:text-zinc-500">
                        No credentials needed
                    </div>
                </div>
            </div>
        );
    }

    // Render custom credential form if one is registered for this node type
    if (CustomCredentialForm) {
        return (
            <div className="space-y-4">
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider mb-2">
                    API Credentials
                </div>
                <Suspense fallback={<div className="h-32" />}>
                    <CustomCredentialForm
                        nodeData={nodeData}
                        credentialIds={credentialIds}
                        onCredentialIdsChange={handleCredentialIdsChange}
                        compact={compact}
                    />
                </Suspense>
            </div>
        );
    }

    // Notice surfaced once at the top of the tab (deduped across required credentials),
    // e.g. an integration that's temporarily unavailable while its OAuth app awaits approval.
    const credentialNotices = Array.from(
        new Set(
            requiredCredentials
                .map((req) => getCredentialNotice(req.schema))
                .filter((notice): notice is string => Boolean(notice))
        )
    );

    return (
        <div className="space-y-4">
            {credentialNotices.map((notice) => (
                <div
                    key={notice}
                    className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2.5"
                >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                    <p className="text-xs leading-[1.55] text-amber-100/90">{notice}</p>
                </div>
            ))}

            {!compact && (
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider mb-2">
                    {usageBasedBillingAvailable ? 'API Credentials' : 'Required Credentials'}
                </div>
            )}

            {requiredCredentials.map((req) => {
                const matchingCredentials = availableCredentials
                    .filter(cred => cred.credential_type === req.credential_type && !cred.over_cap)
                    .sort((a, b) => deadRank(a) - deadRank(b));
                const matchingVars = credentialVariables?.filter(v =>
                    v.credentialTypes.length === 0 || v.credentialTypes.includes(req.credential_type)
                ) ?? [];
                const selectedCredentialId = credentialIds[req.credential_type];
                const selectedCredential = matchingCredentials.find(c => c.id === selectedCredentialId);

                // Filter credentials based on search query
                const filteredCredentials = fuzzyFilter(
                    matchingCredentials,
                    credentialSearchQuery,
                    cred => [{ text: cred.name.toLowerCase(), weight: 1, fuzzy: true }]
                );

                return (
                    <div key={req.credential_type} className="space-y-2">
                        {/* Credential Label (hidden in compact mode — drawer shows its own label).
                            Exception: when multiple credential types are required, show just the
                            row label in compact mode so rows are distinguishable. */}
                        {!compact ? (
                            <div>
                                <div className="text-sm text-foreground font-medium mb-1">
                                    {req.label}
                                </div>
                                <div className="text-xs text-muted-foreground dark:text-zinc-500">
                                    {req.description}
                                </div>
                            </div>
                        ) : requiredCredentials.length > 1 && (
                            <div className="text-xs text-muted-foreground font-medium">
                                {req.label}
                            </div>
                        )}

                        {/* "Get your credentials here" link — shown in both modes so the
                            drawer's compact view still surfaces where to obtain the key. */}
                        {getCredentialUrl(req.schema) && (
                            <a
                                href={getCredentialUrl(req.schema)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
                            >
                                Get your {req.label.toLowerCase().includes('api') ? 'API key' : 'credentials'} here
                                <ExternalLink className="w-3 h-3" />
                            </a>
                        )}

                        {/* Usage-based billing marker — styling matches AgentCredentialsForm
                            so credential-optional nodes read identically to the agent node. */}
                        {usageBasedBillingAvailable && (
                            <p className="text-xs text-green-600 dark:text-green-400">
                                ✓ Usage-based billing available - credentials optional
                            </p>
                        )}
                        {platformKey && (instanceKeyConfigured ? (
                            <p className="text-xs text-green-600 dark:text-green-400">
                                ✓ Runs on this instance&apos;s {providerKeyLabel(platformKey.env)} key — credentials optional
                            </p>
                        ) : (
                            <p className="text-xs text-muted-foreground">
                                Or add one {providerKeyLabel(platformKey.env)} key for the whole instance under Settings → Self-hosted.
                            </p>
                        ))}

                        {/* Credential Selection */}
                        <div className="space-y-2">
                            {(matchingCredentials.length > 0 || matchingVars.length > 0) && (
                                <div className="flex items-center gap-2 max-w-md">
                                    {/* Dropdown */}
                                    <div className="relative flex-1" ref={openDropdownType === req.credential_type ? dropdownRef : null}>
                                        <button
                                            type="button"
                                            data-testid="credential-dropdown"
                                            onClick={() => setOpenDropdownType(openDropdownType === req.credential_type ? null : req.credential_type)}
                                            className="w-full px-3 py-2 text-sm bg-card dark:bg-zinc-900/50 border border-input rounded-lg text-left flex items-center justify-between hover:bg-muted dark:hover:bg-zinc-900 hover:border-foreground/20 transition-all group"
                                        >
                                            <span className={`truncate ${selectedCredentialId?.startsWith('{{') ? "text-emerald-600 dark:text-emerald-300" : selectedCredential?.revoked_at ? "text-red-600 dark:text-red-400" : selectedCredential && isDisconnected(selectedCredential) ? "text-amber-600 dark:text-amber-400" : (selectedCredential || selectedCredentialId) ? "text-foreground/80" : "text-muted-foreground dark:text-zinc-500"}`}>
                                                {selectedCredentialId?.startsWith('{{')
                                                    ? (credentialVariables?.find(v => `{{vars.${v.name}}}` === selectedCredentialId)?.name || selectedCredentialId)
                                                    : selectedCredential ? `${selectedCredential.name}${selectedCredential.revoked_at ? ' (revoked)' : isDisconnected(selectedCredential) ? ' (disconnected)' : ''}` : selectedCredentialId ? "Connected" : "Select credential..."}
                                            </span>
                                            <ChevronDown
                                                className={`h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-all flex-shrink-0 ml-2 ${
                                                    openDropdownType === req.credential_type ? 'rotate-180' : ''
                                                }`}
                                            />
                                        </button>

                                        {/* Dropdown Panel */}
                                        {openDropdownType === req.credential_type && (
                                            <div className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-2xl overflow-hidden animate-fade-in">
                                                {/* Search Input */}
                                                <div className="relative border-b border-border">
                                                    <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                                                    <input
                                                        ref={searchInputRef}
                                                        type="text"
                                                        placeholder="Search..."
                                                        value={credentialSearchQuery}
                                                        onChange={(e) => setCredentialSearchQuery(e.target.value)}
                                                        className="w-full pl-8 pr-2.5 py-2 bg-transparent text-foreground/80 placeholder:text-[hsl(var(--placeholder))] text-xs focus:outline-none"
                                                    />
                                                </div>

                                                <div className="max-h-48 overflow-y-auto scrollbar-subtle">
                                                    {/* Empty Option */}
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            handleCredentialSelect(req.credential_type, '');
                                                            setOpenDropdownType(null);
                                                        }}
                                                        className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center gap-2 group"
                                                    >
                                                        <div className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${!selectedCredentialId ? 'bg-muted-foreground dark:bg-zinc-500' : 'bg-transparent'}`} />
                                                        <span className="text-muted-foreground/70 dark:text-zinc-600 italic">None</span>
                                                    </button>

                                                    {/* Variable References — filtered by credential type */}
                                                    {matchingVars.length > 0 && (<>
                                                        <div className="px-3 py-1.5 text-[10px] text-emerald-600/70 dark:text-emerald-400/70 uppercase tracking-wider border-t border-border/30 dark:border-zinc-800/30">
                                                            Variables
                                                        </div>
                                                        {matchingVars.map((v) => {
                                                            const varRef = `{{vars.${v.name}}}`;
                                                            return (
                                                                <button
                                                                    key={varRef}
                                                                    type="button"
                                                                    onClick={() => {
                                                                        handleCredentialSelect(req.credential_type, varRef);
                                                                        setOpenDropdownType(null);
                                                                    }}
                                                                    className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center gap-2 group border-t border-border/30 dark:border-zinc-800/30"
                                                                >
                                                                    <div className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${selectedCredentialId === varRef ? 'bg-emerald-400' : 'bg-transparent'}`} />
                                                                    <span className="text-emerald-600 dark:text-emerald-300">{v.name}</span>
                                                                </button>
                                                            );
                                                        })}
                                                    </>)}

                                                    {/* Credential Options */}
                                                    {filteredCredentials.length > 0 ? (
                                                        filteredCredentials.map((cred) => (
                                                            <div
                                                                key={cred.id}
                                                                className="flex items-center w-full text-xs hover:bg-accent transition-colors border-t border-border/30 dark:border-zinc-800/30"
                                                            >
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        handleCredentialSelect(req.credential_type, cred.id);
                                                                        setOpenDropdownType(null);
                                                                    }}
                                                                    className="flex-1 min-w-0 px-3 py-2 text-left flex items-center gap-2"
                                                                >
                                                                    <div className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${selectedCredentialId === cred.id ? 'bg-muted-foreground' : 'bg-transparent'}`} />
                                                                    <div className={`truncate ${cred.revoked_at ? 'text-muted-foreground/60 line-through' : isDisconnected(cred) ? 'text-muted-foreground/60' : 'text-foreground/80'}`}>
                                                                        {cred.name}
                                                                    </div>
                                                                    {cred.revoked_at ? (
                                                                        <span
                                                                            className="flex-shrink-0 text-[10px] font-medium text-red-600 dark:text-red-400"
                                                                            title="This credential was disconnected or revoked — reconnect the account to use it again"
                                                                        >
                                                                            Revoked
                                                                        </span>
                                                                    ) : isDisconnected(cred) ? (
                                                                        <span
                                                                            className="flex-shrink-0 text-[10px] font-medium text-amber-600 dark:text-amber-400"
                                                                            title="This WhatsApp connection is no longer linked to a phone — connect a new credential by scanning a fresh QR code"
                                                                        >
                                                                            Disconnected
                                                                        </span>
                                                                    ) : null}
                                                                </button>
                                                                {/* Owner-only controls: hidden for any cred the viewer
                                                                    doesn't own (backend rejects them anyway). */}
                                                                {isOwnedByViewer(cred) && (
                                                                <div className="flex items-center gap-0.5 pr-1.5">
                                                                    <button
                                                                        type="button"
                                                                        onClick={(e) => {
                                                                            e.stopPropagation();
                                                                            setShareCredential({ id: cred.id, name: cred.name });
                                                                            setOpenDropdownType(null);
                                                                        }}
                                                                        className="p-1 rounded text-muted-foreground dark:text-zinc-500 hover:bg-accent dark:hover:bg-zinc-700 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                                                                        title="Share credential"
                                                                    >
                                                                        <Share2 className="h-3 w-3" />
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        onClick={(e) => {
                                                                            e.stopPropagation();
                                                                            openDeleteDialog(cred.id, cred.name, req.credential_type);
                                                                            setOpenDropdownType(null);
                                                                        }}
                                                                        className="p-1 rounded text-muted-foreground dark:text-zinc-500 hover:bg-accent dark:hover:bg-zinc-700 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                                                                        title="Delete credential"
                                                                    >
                                                                        <Trash2 className="h-3 w-3" />
                                                                    </button>
                                                                </div>
                                                                )}
                                                            </div>
                                                        ))
                                                    ) : (
                                                        credentialSearchQuery && (
                                                            <div className="px-3 py-2 text-xs text-muted-foreground/70 dark:text-zinc-600 italic border-t border-border/30 dark:border-zinc-800/30">
                                                                No match
                                                            </div>
                                                        )
                                                    )}
                                                </div>

                                                {/* Persistent "Create new" footer — outside the scroll area so it stays visible.
                                                    Hidden for QR-scan credentials, which are connected via the always-visible
                                                    QR form below. For OAuth, kick off the connect flow directly when possible;
                                                    for providers that need an extra input (Shopify shop, Atlassian site),
                                                    just close the dropdown so the input is reachable. */}
                                                {!isQRScanCredential(req.schema) && (
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            if (!canCreateCredential(req.credential_type)) return;
                                                            setOpenDropdownType(null);
                                                            setCredentialSearchQuery('');

                                                            if (isOAuthCredential(req.schema)) {
                                                                const provider = getOAuthProvider(req.schema);
                                                                if (!provider) return;
                                                                if (provider === 'shopify' || provider === 'atlassian' || provider === 'zendesk') return;
                                                                const scopes = getOAuthScopes(req.schema);
                                                                const userScopes = getOAuthUserScopes(req.schema);
                                                                const defaultName = `${req.label} - ${new Date().toLocaleDateString()}`;
                                                                oauthConnect(provider, defaultName, scopes, undefined, undefined, userScopes);
                                                            } else {
                                                                setCreatingCredentialType(req.credential_type);
                                                            }
                                                        }}
                                                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground border-t border-border"
                                                    >
                                                        <Plus className="h-3.5 w-3.5" />
                                                        {isOAuthCredential(req.schema) ? `Connect new ${req.label}` : `Create new ${req.label}`}
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>

                                    {/* Edit/Share/Delete Actions - only for the viewer's OWN credential.
                                        The backend rejects edit/share/delete from a non-owner, so hide
                                        these dead-end controls (the owner note already explains why). */}
                                    {selectedCredential && isOwnedByViewer(selectedCredential) && editingCredentialId !== selectedCredential.id && (
                                        <div className="flex items-center gap-1">
                                            <button
                                                onClick={() => startEditCredential(selectedCredential, req)}
                                                className="p-2 hover:bg-accent rounded-lg transition-colors"
                                                title="Edit credential"
                                            >
                                                <Edit2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80" />
                                            </button>
                                            <button
                                                onClick={() => setShareCredential({ id: selectedCredential.id, name: selectedCredential.name })}
                                                className="p-2 hover:bg-accent rounded-lg transition-colors"
                                                title="Share credential"
                                            >
                                                <Share2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 hover:text-blue-600 dark:hover:text-blue-400" />
                                            </button>
                                            <button
                                                onClick={() => openDeleteDialog(selectedCredential.id, selectedCredential.name, req.credential_type)}
                                                className="p-2 hover:bg-accent rounded-lg transition-colors"
                                                title="Delete credential"
                                            >
                                                <Trash2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 hover:text-red-600 dark:hover:text-red-400" />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Subtle owner note: why the owner-only controls above are
                                absent. `owner_name` marks a run-as-owner cred (shared into
                                this flow); otherwise it was shared with the viewer directly. */}
                            {selectedCredential && !isOwnedByViewer(selectedCredential) && (
                                <p className="text-[11px] leading-relaxed text-muted-foreground dark:text-zinc-500 max-w-md">
                                    Owned by <span className="text-foreground/80">{ownerLabel(selectedCredential)}</span>.{' '}
                                    {selectedCredential.owner_name
                                        ? "It's shared with this flow."
                                        : "It's shared with you — remove it from Settings → Credentials."}
                                </p>
                            )}

                            {/* Attached-credential health: a revoked (or vanished)
                                credential must say WHY runs will fail, not sit
                                behind a bare "Connected". Empty list = not loaded
                                yet, so no unknown-alarm before data arrives. */}
                            {(() => {
                                if (!selectedCredentialId || selectedCredentialId.startsWith('{{')) return null;
                                // Look up in the FULL list (not the type+cap-filtered
                                // view) so an over-cap credential doesn't false-alarm
                                // as missing.
                                const fullRow = availableCredentials.find(c => c.id === selectedCredentialId);
                                const health = fullRow?.revoked_at
                                    ? 'revoked'
                                    : fullRow && isDisconnected(fullRow)
                                        ? 'disconnected'
                                        : !fullRow && availableCredentials.length > 0
                                            ? 'unknown'
                                            : 'ok';
                                if (health === 'ok') return null;
                                const isAmber = health === 'disconnected';
                                return (
                                    <div
                                        data-testid="credential-health-warning"
                                        className={`flex items-start gap-2 max-w-md rounded-lg border px-3 py-2 text-xs ${isAmber
                                            ? 'border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400'
                                            : 'border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400'}`}
                                    >
                                        <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                                        <span>
                                            {health === 'disconnected'
                                                // The provider check ships its own repair guidance (re-scan this
                                                // WhatsApp credential, reinstall the Discord bot); the wire model
                                                // guarantees one for every dropped verdict.
                                                ? fullRow?.connection_hint ?? 'This connection has dropped and nothing is arriving through it. Reconnect the same credential below.'
                                                : health === 'revoked'
                                                    ? 'This credential was disconnected or revoked and can no longer be used — reconnect the account below or pick another credential.'
                                                    : 'The attached credential no longer exists or is not accessible — reconnect the account below or pick another credential.'}
                                        </span>
                                    </div>
                                );
                            })()}

                            {/* OAuth Credential Connection */}
                            {isOAuthCredential(req.schema) ? (
                                (() => {
                                    const provider = getOAuthProvider(req.schema);
                                    if (!provider) return null;
                                    const providerConfigData = getProviderConfig(provider);
                                    // For Atlassian, pick the product-specific config (confluence
                                    // vs jira) so the button name/icon are correct.
                                    const credSpecificConfig =
                                        provider === 'atlassian' && req.credential_type?.startsWith('confluence')
                                            ? getProviderConfig('confluence')
                                            : providerConfigData;
                                    // Fall back to the node-backed brand icon for providers not in the OAuth map.
                                    const credIcon = getCredentialIcon(req.credential_type);
                                    const ProviderIcon = credSpecificConfig?.Icon || providerConfigData?.Icon || credIcon.Icon;
                                    const providerIconColor = credSpecificConfig?.iconColor || providerConfigData?.iconColor;
                                    const providerName = credSpecificConfig?.name || providerConfigData?.name || req.label || 'your account';
                                    return (
                                        <div className="max-w-md space-y-3">
                                            {/* Connected account info when a credential is selected */}
                                            {selectedCredential && selectedCredential.metadata?.email && (
                                                <div className="mb-2 flex items-center gap-1.5">
                                                    <CheckCircle2 className="h-3 w-3 text-muted-foreground dark:text-zinc-500 flex-shrink-0" />
                                                    <span className="text-[11px] text-muted-foreground dark:text-zinc-500">
                                                        {selectedCredential.metadata.email}
                                                    </span>
                                                </div>
                                            )}
                                            <OAuthConnectForm
                                                provider={provider}
                                                credentialType={req.credential_type}
                                                displayName={providerName}
                                                Icon={ProviderIcon}
                                                iconColor={providerIconColor}
                                                scopes={getOAuthScopes(req.schema)}
                                                userScopes={getOAuthUserScopes(req.schema)}
                                                supportsCustomClient={req.schema?.['x-oauth-supports-custom-client'] === true}
                                                requiresCustomClient={req.schema?.['x-oauth-requires-custom-client'] === true}
                                                redirectUri={req.schema?.['x-oauth-redirect-uri'] as string | undefined}
                                                hasExistingCredential={matchingCredentials.length > 0}
                                                connect={oauthConnect}
                                                connectOrgConsent={connectOrgConsent}
                                                connectingProvider={connectingProvider}
                                                isConnecting={oauthIsConnecting}
                                                error={oauthError || createError || validationError?.message}
                                                errorHelpUrl={validationError?.helpUrl}
                                                onClearError={() => { clearOAuthError(); setCreateError(null); setValidationError(null); }}
                                                pendingSelection={pendingSelection}
                                                onResolvePendingSelection={resolvePendingSelection}
                                                onCancel={cancelOAuthConnect}
                                                canConnect={() => canCreateCredential(req.credential_type)}
                                                // Self-hosted: no OAuth app yet → ask for it right here, not in Settings.
                                                canConfigureInstanceApp={isLocalEdition()}
                                            />
                                        </div>
                                    );
                                })()
                            ) : isQRScanCredential(req.schema) ? (
                                <WhatsAppQRCredentialForm
                                    credentialType={req.credential_type}
                                    // Attached credential with a dead session → the scan
                                    // REPAIRS it in place instead of minting a duplicate.
                                    reconnectCredentialId={(() => {
                                        const attached = availableCredentials.find(c => c.id === selectedCredentialId);
                                        return attached && isDisconnected(attached) && !attached.revoked_at
                                            ? attached.id : undefined;
                                    })()}
                                    onCredentialCreated={(credentialId) => {
                                        handleCredentialSelect(req.credential_type, credentialId);
                                        loadCredentials();
                                    }}
                                />
                            ) : (
                                /* Standard Form-Based Credential Creation */
                                <>
                                    {creatingCredentialType === req.credential_type ? (
                                        <CredentialCreatePanel
                                            label={req.label}
                                            schema={req.schema}
                                            fields={getFieldsFromSchema(req.schema)}
                                            onCancel={cancelCreate}
                                            onSave={(name, data) => handleCreateCredential(req, name, data)}
                                        />
                                    ) : (
                                        /* Standalone "Create new" entry point. Always visible (not just when
                                            no credentials exist) so users can add another credential without
                                            having to discover the dropdown's hidden footer option. Label adapts
                                            to "Create another" when credentials already exist, matching the
                                            OAuth "Connect Another Account" pattern. */
                                        <div className="max-w-md">
                                            <CredentialCreateEntryButton
                                                label={matchingCredentials.length > 0 ? 'Create another' : 'Create new'}
                                                onClick={() => {
                                                    if (!canCreateCredential(req.credential_type)) return;
                                                    setCreatingCredentialType(req.credential_type);
                                                }}
                                            />
                                        </div>
                                    )}
                                </>
                            )}
                        </div>

                        {/* Usage-based billing note (no credential selected, not creating) */}
                        {usageBasedBillingAvailable && !selectedCredentialId && creatingCredentialType !== req.credential_type && (
                            <div className="max-w-md text-xs text-muted-foreground dark:text-zinc-500 bg-card dark:bg-zinc-800/30 border border-border/60 dark:border-transparent rounded-lg px-3 py-2">
                                Using NoClick's usage-based billing (no credentials needed)
                            </div>
                        )}

                        {/* Edit Credential Form */}
                        {selectedCredential && editingCredentialId === selectedCredential.id && (
                            <div className="p-4 rounded-lg bg-muted/50 dark:bg-zinc-900/50 border border-border space-y-3 max-w-md">
                                <div className="flex items-center justify-between mb-2">
                                    <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                                        Edit Credential
                                    </div>
                                    <button
                                        onClick={cancelEdit}
                                        className="p-1 hover:bg-accent rounded transition-colors"
                                    >
                                        <X className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
                                    </button>
                                </div>

                                {/* Security Warning */}
                                <div className="p-2 rounded bg-amber-500/10 border border-amber-500/20">
                                    <div className="text-[10px] text-amber-700 dark:text-amber-500">
                                        For security, you must re-enter all credential values
                                    </div>
                                </div>

                                {/* Use custom OAuth form for credentials that support custom client */}
                                {req.schema?.['x-oauth-supports-custom-client'] ? (
                                    <OAuthCredentialForm
                                        schema={req.schema}
                                        formData={editCredentialFormData}
                                        onFormDataChange={updateEditField}
                                        credentialName={editCredentialName}
                                        onCredentialNameChange={setEditCredentialName}
                                        label={req.label}
                                    />
                                ) : (
                                    <>
                                        {/* Credential Name */}
                                        <div className="space-y-1.5">
                                            <label className="block text-xs text-muted-foreground dark:text-zinc-500">
                                                Name
                                            </label>
                                            <input
                                                type="text"
                                                value={editCredentialName}
                                                onChange={(e) => setEditCredentialName(e.target.value)}
                                                placeholder={`My ${req.label}`}
                                                className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors"
                                            />
                                        </div>

                                        {/* Credential Fields */}
                                        {getFieldsFromSchema(req.schema).map((field) => (
                                            <CredentialFieldInput
                                                key={field.name}
                                                field={field}
                                                value={editCredentialFormData[field.name] || ''}
                                                onChange={(v) => updateEditField(field.name, v)}
                                            />
                                        ))}
                                    </>
                                )}

                                {/* Error Message */}
                                {editError && (
                                    <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                                        <div className="text-xs text-red-500">{editError}</div>
                                    </div>
                                )}

                                {/* Actions */}
                                <div className="flex gap-2 pt-1">
                                    <button
                                        onClick={cancelEdit}
                                        className="flex-1 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        onClick={() => handleUpdateCredential(req)}
                                        disabled={editLoading || getFieldsFromSchema(req.schema).filter(f => f.required).some(f => !editCredentialFormData[f.name])}
                                        className="flex-1 px-3 py-2 text-xs text-primary-foreground dark:text-foreground bg-primary dark:bg-zinc-700 hover:bg-primary/90 dark:hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground/70 dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-transparent dark:border-zinc-700 disabled:border-border rounded-lg transition-all flex items-center justify-center gap-1.5"
                                    >
                                        {editLoading ? (
                                            'Updating...'
                                        ) : (
                                            <>
                                                <Check className="h-3 w-3" />
                                                Update
                                            </>
                                        )}
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}

            {/* Ask someone else for the credential (hidden in compact mode) */}
            {!compact && requiredCredentials.length > 0 && (
                <CredentialRequestActions credentialType={requiredCredentials[0].credential_type} />
            )}

            {/* Delete Confirmation Dialog */}
            <DeleteConfirmPopup
                itemType="Credential"
                itemName={credentialToDelete?.name}
                isOpen={isDeleteDialogOpen}
                onOpenChange={setIsDeleteDialogOpen}
                onConfirmDelete={confirmDeleteCredential}
            />

            {/* Share Dialog */}
            <ShareDialog
                isOpen={!!shareCredential}
                onOpenChange={(open) => !open && setShareCredential(null)}
                resource={shareCredential}
                resourceType="credential"
            />

            <UpgradePopup
                isOpen={!!planLimitError || !!oauthPlanLimitError}
                onOpenChange={(open) => { if (!open) { setPlanLimitError(null); clearOAuthError(); } }}
                errorMessage={planLimitError || oauthPlanLimitError || ''}
            />
        </div>
    );
};
