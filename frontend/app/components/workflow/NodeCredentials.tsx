// The node panel's account for a node: which of your accounts it runs as (a picker per kind of account that has
// any), what connecting it proved, and connecting another through the same flow the Connections dialog uses
// (AppConnect: a switch between the ways in, a key as get-it-then-paste-it steps, asking someone who can).
// Supports custom credential forms for nodes with special requirements (e.g., agent nodes).

import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';
import { Plus, AlertCircle, X, Check, Edit2, Trash2, ChevronDown, Search, Share2, Info } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { INLINE_ACTION } from './CredentialRequestActions';
import { appNameOf, credentialRequirements, getFieldsFromSchema, methodFromRequirement, type CredentialRequirement } from '~/components/credential/credentialMethods';
import { CREATE_FORM, CredentialCreatePanel, type CredentialSaveResult } from '~/components/credential/CredentialCreatePanel';
import { ConnectionVerdict, StoredVerdict } from '~/components/credential/ConnectionVerdict';
import { AppConnect } from '~/components/credential/connect/AppConnect';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import {
    claudePlanRefusal,
    getAgentConfigRecord,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    inferProviderFromPrefix,
    isPrimaryAgentCredentialKey,
} from '~/lib/agentCredentialModel';
import { isCliAgentModel } from '~/lib/agentChat';
import { useCredentialOAuth, type Credential } from '~/hooks/useCredentialOAuth';
import { useCredentialSchemaVisible } from '~/hooks/useCredentialSchemaVisible';
import { useSnapshot } from 'valtio';
import { isLocalEdition } from '~/lib/edition';
import { instanceKeysStore, platformKeyFunds, platformKeyMarker, type PlatformKeyMarker } from '~/lib/instanceKeys';
import { providerKeyLabel } from '~/lib/providerKeys';
import { InstanceKeyPrompt } from '~/components/credential/InstanceKeyPrompt';
import { InstanceSmtpForm } from '~/components/credential/InstanceSmtpForm';
// Lazy: the agent credential form pulls useModels (~159KB gz) which otherwise
// evaluated eagerly on the dashboard via the always-mounted credential dialog.
// It only renders when configuring an agent (LLM) credential.
const AgentCredentialsForm = lazy(() =>
    import('./AgentCredentialsForm').then((m) => ({ default: m.AgentCredentialsForm }))
);
import { OAuthCredentialForm } from './OAuthCredentialForm';
import { MCPCredentialForm } from './MCPCredentialForm';
import { invalidateCredentialsCache, removeCredentialsFromCache, isConnectionDropped, type CredentialDisplayMeta } from '~/utils/credentialAutoSelect';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { methodName, copyMethodOf } from '~/utils/credentialCopy';
import { FIELD_LABEL } from '~/components/shell/fields';
import { cn } from '~/lib/utils';
import { hasCustomCredentialForm, type CustomCredentialFormType } from './customCredentialForms';
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
    /** Hears an account the person just connected here (a sign-in that returned, a key that saved), never one picked
        from the list. */
    onConnected?: (credentialId: string) => void;
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
 * Registry of custom credential form components by node type (the types are listed in customCredentialForms).
 * Nodes listed here will use their custom form instead of the default credential UI.
 * Custom forms must implement CustomCredentialFormProps interface.
 */
const CUSTOM_CREDENTIAL_FORMS: Record<
    CustomCredentialFormType,
    ComponentType<CustomCredentialFormProps> | LazyExoticComponent<ComponentType<CustomCredentialFormProps>>
> = {
    'agent': AgentCredentialsForm,
    'mcp-server': MCPCredentialFormWrapper,
};

export { hasCustomCredentialForm };

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
 * auth (see isPrimaryAgentCredentialKey), and neither does a Claude plan on an
 * anthropic/* model outside Claude Code (claudePlanRefusal).
 */
function agentRequiresCredentials(nodeData: Record<string, any>, credentialIds: Record<string, string>): boolean {
    const config = getAgentConfigRecord(nodeData);
    const hasPrimaryCredential = Object.entries(credentialIds).some(
        ([key, id]) => isPrimaryAgentCredentialKey(key) && id && id.trim() !== ''
    );
    const refusedPlan = claudePlanRefusal(
        credentialIds,
        inferProviderFromPrefix(getAgentEffectiveModel(undefined, config))
    );
    if (hasPrimaryCredential && !refusedPlan) return false;

    return isCliAgentModel(getAgentSelectedModel(undefined, config));
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
            // Optional in the cloud because NoClick's key pays; on a self-hosted instance only while the operator
            // configured that key.
            return optional && platformKeyFunds(platformKeyMarker(def));
        }
    }

    return false;
}

/** The platform key the selected operation runs on, if it declares one. */
export function operationPlatformKey(nodeType: string, nodeData?: Record<string, unknown>): PlatformKeyMarker | null {
    type OperationDef = Record<string, unknown> & { properties?: { operation?: { const?: unknown; default?: unknown } } };
    const operation = nodeData?.operation as string | undefined;
    const schema = NODE_SCHEMAS[nodeType];
    const oneOf = schema?.properties?.config?.oneOf as Array<{ $ref?: string }> | undefined;
    const defs = (schema as { $defs?: Record<string, OperationDef> } | undefined)?.$defs;
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
    if (isLocalEdition()) return false; // NoClick's own key pays only on the hosted service
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
// Edit/Share/Delete are owner-only (the backend rejects them from anyone else).
// Gate on the backend's ownership signals, NOT on `owner_name` — that label is
// only set on injected run-as-owner descriptors, so a credential shared with the
// viewer directly has none and would wrongly show dead-end controls.
const isOwnedByViewer = (cred: Credential): boolean =>
    cred.access_type === 'owner' || cred.owned_by_me === true;

const ownerLabel = (cred: Credential): string =>
    cred.owner_name || cred.shared_by_name || cred.shared_by_email || 'another user';

const isQRScanCredential = (credentialSchema: { 'x-credential-type'?: string } | null | undefined): boolean =>
    kindFromCredentialType(credentialSchema?.['x-credential-type']) === 'qr_scan';

// A notice shown above the ways in (e.g. an integration pending approval / unavailable).
const getCredentialNotice = (credentialSchema: { 'x-credential-notice'?: string } | null | undefined): string | undefined => credentialSchema?.['x-credential-notice'];

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
    /** Compact mode (the builder's ask drawer, the Setup step): no labels where the host has its own, no asking
     *  someone else. */
    compact?: boolean;
    /** What the connect-time probe proved about a credential just created or
        re-keyed here (null = nothing could be judged), so hosts like the Setup
        step can show the verdict without a second provider round-trip. */
    onVerification?: (credentialId: string, verification: CredentialTestConnectionResponse | null) => void;
    /** Hears an account the person just connected here (a sign-in, a key, a scan, a purchase), never one picked from
        the list: the builder's one-question ask takes it as the answer. */
    onConnected?: (credentialId: string) => void;
}

export const NodeCredentials = ({ nodeType, nodeData = {}, credentialIds = {}, onChange, credentialVariables, compact, onVerification, onConnected }: NodeCredentialsProps) => {
    const isCredentialSchemaVisible = useCredentialSchemaVisible();
    // Read from the bundled schemas while rendering, so the first frame never claims a step needs no account.
    const { requiredCredentials, error } = useMemo(() => {
        try {
            return { requiredCredentials: credentialRequirements(nodeType, isCredentialSchemaVisible), error: null };
        } catch (err) {
            console.error('[NodeCredentials] Error loading schema:', err);
            return { requiredCredentials: [] as CredentialRequirement[], error: err instanceof Error ? err.message : 'Failed to load schema' };
        }
    }, [nodeType, isCredentialSchemaVisible]);
    const usageBasedBillingAvailable = useMemo(
        () => isUsageBasedBillingAvailable(nodeType, nodeData),
        [nodeType, nodeData]
    );
    const app = useMemo(() => appNameOf(nodeType), [nodeType]);
    // Self-hosted: a platform-keyed operation runs on the INSTANCE's key, which the store flips the moment one is
    // saved anywhere.
    const instanceKeys = useSnapshot(instanceKeysStore);
    const selfHosted = isLocalEdition();
    const platformKey = useMemo(() => (selfHosted ? operationPlatformKey(nodeType, nodeData) : null), [selfHosted, nodeType, nodeData]);
    const instanceKeyConfigured = !!platformKey && instanceKeys.configured.includes(platformKey.env);
    const outboundEmailConfigured =
        instanceKeys.configured.includes('FROM_EMAIL') && (instanceKeys.configured.includes('SMTP_HOST') || instanceKeys.configured.includes('RESEND_API_KEY'));

    // Check if this node type has a custom credential form
    const CustomCredentialForm = hasCustomCredentialForm(nodeType) ? CUSTOM_CREDENTIAL_FORMS[nodeType as CustomCredentialFormType] : undefined;

    // Stable callback for credential ID changes (used by custom forms)
    const handleCredentialIdsChange = useCallback((newCredentialIds: Record<string, string>) => {
        onChange?.(newCredentialIds);
    }, [onChange]);

    // Ref to track required credentials for selection cleanup
    const requiredCredentialsRef = useRef<CredentialRequirement[]>([]);
    useEffect(() => {
        requiredCredentialsRef.current = requiredCredentials;
    }, [requiredCredentials]);

    // Ref to the resolved credential list so handleCredentialSelect can build a display descriptor for the selected
    // credential.
    const availableCredentialsRef = useRef<Credential[]>([]);
    // Credentials minted from this panel (a sign-in, a key, a bought number, a scanned QR): selected before the
    // refreshed list contains them, so the missing-credential warning must not judge them by the stale list.
    const mintedCredentialIdsRef = useRef<Set<string>>(new Set());

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

    // The account list (connecting itself runs in AppConnect).
    const { availableCredentials, loading, loadCredentials } = useCredentialOAuth();
    availableCredentialsRef.current = availableCredentials;

    // Note: an owner's credential set on a node is resolved as the workflow owner
    // at execution and is NOT shared into a collaborator's account, so it won't be
    // in their credential:list. Its display info (name + owner tag) is fetched
    // workflow-scoped by FlowCanvas (credential:display_info) and merged into the
    // cache → availableCredentials, so the dropdown resolves it here.

    // The connect flow, open on a way in (its credential type), or on the first; closed once an account exists.
    const [connecting, setConnecting] = useState<string | true | null>(null);

    // Edit state
    const [editingCredentialId, setEditingCredentialId] = useState<string | null>(null);
    // Connect-time verdicts for credentials created or re-keyed in this
    // session, by id. Older credentials carry theirs in metadata.verified_as.
    const [verifications, setVerifications] = useState<Record<string, CredentialTestConnectionResponse | null>>({});
    const recordVerification = useCallback((credentialId: string, verification: CredentialTestConnectionResponse | null | undefined) => {
        setVerifications(prev => ({ ...prev, [credentialId]: verification ?? null }));
        onVerification?.(credentialId, verification ?? null);
    }, [onVerification]);
    // The custom-client OAuth edit form's values (every other edit is the connect form).
    const [editCredentialName, setEditCredentialName] = useState('');
    const [editCredentialFormData, setEditCredentialFormData] = useState<Record<string, string>>({});

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

    // Edit credential handlers
    const startEditCredential = useCallback((credential: Credential) => {
        setEditingCredentialId(credential.id);
        setEditCredentialName(credential.name);
        // Values start empty: the user re-enters them, since NoClick never shows a saved secret.
        setEditCredentialFormData({});
    }, []);

    const cancelEdit = useCallback(() => {
        setEditingCredentialId(null);
        setEditCredentialName('');
        setEditCredentialFormData({});
    }, []);

    // A re-keyed secret is judged like a new one: field verdicts under their inputs, the provider's refusal under the
    // form, and what it proved once it lands.
    const updateCredential = useCallback(async (name: string, data: Record<string, string>): Promise<CredentialSaveResult> => {
        const credentialId = editingCredentialId;
        if (!credentialId) return null;
        try {
            const response = await sendEventAsync({
                event_name: 'credential:update',
                request_id: `update-cred-${Date.now()}`,
                credential_id: credentialId,
                name: name || undefined,
                credential_data: data,
            });
            if (response?.success) {
                invalidateCredentialsCache();
                await loadCredentials();
                recordVerification(credentialId, response.verification);
                cancelEdit();
                return null;
            }
            return {
                error: response?.error || response?.message || 'Failed to update credential',
                fieldErrors: response?.field_errors ?? null,
                hint: response?.hint ?? null,
                rejected: response?.reachable === false,
            };
        } catch (err) {
            console.error('[NodeCredentials] Error updating credential:', err);
            return err instanceof Error ? err.message : 'Failed to update credential';
        }
    }, [editingCredentialId, loadCredentials, recordVerification, cancelEdit]);

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
        return <div className="py-6 text-center text-[13px] text-muted-foreground">Loading your accounts…</div>;
    }

    if (error) {
        return (
            <p role="alert" className="flex items-center gap-2 text-[13px] text-red-600 dark:text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
            </p>
        );
    }

    // Render custom credential form if one is registered for this node type
    if (CustomCredentialForm) {
        return (
            <Suspense fallback={<div className="h-32" />}>
                <CustomCredentialForm
                    nodeData={nodeData}
                    credentialIds={credentialIds}
                    onCredentialIdsChange={handleCredentialIdsChange}
                    compact={compact}
                    onConnected={onConnected}
                />
            </Suspense>
        );
    }

    // Self-hosted Send Email: no account, but the instance needs somewhere to send from.
    if (selfHosted && nodeType === 'automation-send-email') {
        return outboundEmailConfigured ? (
            <p className="text-[13px] leading-relaxed text-muted-foreground">Sends through this instance’s mail server; change it under Settings → Self-hosted.</p>
        ) : (
            <div className="max-w-xl">
                <InstanceSmtpForm />
            </div>
        );
    }

    // Self-hosted, an operation the node's own account can't fund (LinkedIn scraping runs on Apify): the instance's
    // key, not an account.
    if (platformKey && !platformKey.byok) {
        const label = providerKeyLabel(platformKey.env);
        return instanceKeyConfigured ? (
            <p className="text-[13px] leading-relaxed text-muted-foreground">Runs on this instance’s {label} key. No account needed.</p>
        ) : (
            <div className="max-w-xl">
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

    if (requiredCredentials.length === 0) {
        return <p className="py-6 text-center text-[13px] text-muted-foreground">This step needs no account.</p>;
    }

    // Notice surfaced once (deduped across the ways in), e.g. an integration that's temporarily unavailable while its
    // OAuth app awaits approval.
    const credentialNotices = Array.from(
        new Set(
            requiredCredentials
                .map((req) => getCredentialNotice(req.schema))
                .filter((notice): notice is string => Boolean(notice))
        )
    );

    // A picker for each kind of account the viewer has (or the node already points at).
    const pickers = requiredCredentials
        .map((req) => ({
            req,
            matching: availableCredentials
                .filter(cred => cred.credential_type === req.credential_type && !cred.over_cap)
                .sort((a, b) => deadRank(a) - deadRank(b)),
            vars: credentialVariables?.filter(v => v.credentialTypes.length === 0 || v.credentialTypes.includes(req.credential_type)) ?? [],
        }))
        .filter(({ req, matching, vars }) => matching.length > 0 || vars.length > 0 || !!credentialIds[req.credential_type]);

    // A WhatsApp number whose session died is repaired by scanning again in place, never by minting a duplicate.
    const qrRepair = requiredCredentials
        .filter((req) => isQRScanCredential(req.schema))
        .map((req) => availableCredentials.find((c) => c.id === credentialIds[req.credential_type]))
        .find((cred): cred is Credential => !!cred && isDisconnected(cred) && !cred.revoked_at);

    // The health of what the node points at: a revoked (or vanished) credential says why runs will fail.
    const healthOf = (selectedCredentialId: string | undefined): 'ok' | 'revoked' | 'disconnected' | 'unknown' => {
        if (!selectedCredentialId || selectedCredentialId.startsWith('{{')) return 'ok';
        // Look up in the FULL list (not the type+cap-filtered view) so an over-cap credential doesn't false-alarm.
        const fullRow = availableCredentials.find(c => c.id === selectedCredentialId);
        // A credential this panel just minted is real before the list refresh lands.
        const justMinted = mintedCredentialIdsRef.current.has(selectedCredentialId);
        if (fullRow?.revoked_at) return 'revoked';
        if (fullRow && isDisconnected(fullRow)) return 'disconnected';
        if (!fullRow && availableCredentials.length > 0 && !justMinted) return 'unknown';
        return 'ok';
    };
    const anyUnhealthy = requiredCredentials.some((req) => healthOf(credentialIds[req.credential_type]) !== 'ok');
    // A spare QR invites a re-scan that rebinds a working number to a new connection, so one shows unasked only when
    // no usable number exists, or to repair a dead one.
    const usableNumber = requiredCredentials
        .filter((req) => isQRScanCredential(req.schema))
        .some((req) => availableCredentials.some((c) => c.credential_type === req.credential_type && !c.over_cap && !c.revoked_at && !isDisconnected(c)));
    const connectOpen = connecting !== null || pickers.length === 0 || anyUnhealthy || !!qrRepair;

    const editing = pickers.flatMap(({ req, matching }) => matching.filter((c) => c.id === editingCredentialId).map((cred) => ({ req, cred })))[0];

    return (
        // A form's measure, not the panel's: the node panel can span the whole canvas.
        <div className="max-w-xl space-y-5" data-testid="node-credentials">
            {credentialNotices.map((notice) => (
                <p key={notice} className="flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground">
                    <Info className="mt-0.5 h-4 w-4 shrink-0" />
                    {notice}
                </p>
            ))}

            {usageBasedBillingAvailable && (
                <p className="text-[13px] leading-relaxed text-muted-foreground">
                    Optional. With no account here, NoClick’s own key runs it and bills the usage.
                </p>
            )}
            {platformKey && (
                <p className="text-[13px] leading-relaxed text-muted-foreground">
                    {instanceKeyConfigured
                        ? `Optional. With no account here, this instance’s ${providerKeyLabel(platformKey.env)} key runs it.`
                        : `Or add one ${providerKeyLabel(platformKey.env)} key for the whole instance under Settings → Self-hosted.`}
                </p>
            )}

            {pickers.map(({ req, matching, vars }) => {
                const selectedCredentialId = credentialIds[req.credential_type];
                const selectedCredential = matching.find(c => c.id === selectedCredentialId);
                const health = healthOf(selectedCredentialId);
                const filteredCredentials = fuzzyFilter(
                    matching,
                    credentialSearchQuery,
                    cred => [{ text: cred.name.toLowerCase(), weight: 1, fuzzy: true }]
                );
                // One picker reads "Account"; several are named by their way in ("Sign in with Notion", "Integration token").
                const label = pickers.length > 1 ? methodName(copyMethodOf(methodFromRequirement(req)), app) : 'Account';

                if (editing?.req === req) {
                    return (
                        <div key={req.credential_type} className="space-y-3">
                            <div className="flex items-center justify-between">
                                <p className="text-[14.5px] font-medium text-foreground">Update {editing.cred.name}</p>
                                <button type="button" onClick={cancelEdit} aria-label="Close" className={CREATE_FORM.close}>
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            </div>
                            {req.schema?.['x-oauth-supports-custom-client'] ? (
                                // A sign-in through your own OAuth app keeps that app's own form.
                                <div className={CREATE_FORM.root}>
                                    <OAuthCredentialForm
                                        schema={req.schema}
                                        formData={editCredentialFormData}
                                        onFormDataChange={(field: string, value: string) => setEditCredentialFormData(prev => ({ ...prev, [field]: value }))}
                                        credentialName={editCredentialName}
                                        onCredentialNameChange={setEditCredentialName}
                                        label={req.label}
                                    />
                                    <div className={CREATE_FORM.actions}>
                                        <button type="button" onClick={cancelEdit} className={CREATE_FORM.cancel}>Cancel</button>
                                        <button type="button" onClick={() => void updateCredential(editCredentialName, editCredentialFormData)} className={CREATE_FORM.save}>
                                            <Check className="h-3 w-3" />
                                            Save
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <CredentialCreatePanel
                                    fields={getFieldsFromSchema(req.schema)}
                                    app={app}
                                    name={editing.cred.name}
                                    note="Enter every value again: NoClick never shows a saved secret."
                                    saveLabel="Save"
                                    onCancel={cancelEdit}
                                    onSave={updateCredential}
                                />
                            )}
                        </div>
                    );
                }

                return (
                    <div key={req.credential_type}>
                        {(!compact || pickers.length > 1) && <div className={FIELD_LABEL}>{label}</div>}
                        <div className="flex items-center gap-1.5">
                            <div className="relative min-w-0 flex-1" ref={openDropdownType === req.credential_type ? dropdownRef : null}>
                                <button
                                    type="button"
                                    data-testid="credential-dropdown"
                                    aria-haspopup="listbox"
                                    aria-expanded={openDropdownType === req.credential_type}
                                    onClick={() => setOpenDropdownType(openDropdownType === req.credential_type ? null : req.credential_type)}
                                    className="group flex h-10 w-full items-center justify-between rounded-xl border border-border bg-transparent px-3.5 text-left text-[14px] transition-colors hover:border-foreground/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-foreground/[0.1]"
                                >
                                    <span className={cn('truncate', selectedCredentialId?.startsWith('{{') ? 'text-emerald-600 dark:text-emerald-300' : selectedCredential?.revoked_at || (selectedCredential && isDisconnected(selectedCredential)) ? 'text-red-600 dark:text-red-400' : selectedCredential || selectedCredentialId ? 'text-foreground' : 'text-muted-foreground')}>
                                        {selectedCredentialId?.startsWith('{{')
                                            ? (credentialVariables?.find(v => `{{vars.${v.name}}}` === selectedCredentialId)?.name || selectedCredentialId)
                                            : selectedCredential ? `${selectedCredential.name}${selectedCredential.revoked_at ? ' (revoked)' : isDisconnected(selectedCredential) ? ' (disconnected)' : ''}` : selectedCredentialId ? 'Connected' : 'Choose an account'}
                                    </span>
                                    <ChevronDown className={cn('ml-2 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:text-foreground', openDropdownType === req.credential_type && 'rotate-180')} />
                                </button>

                                {openDropdownType === req.credential_type && (
                                    <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-xl border border-border bg-popover shadow-lg animate-fade-in dark:border-foreground/[0.1]">
                                        <div className="relative border-b border-border dark:border-foreground/[0.08]">
                                            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                                            <input
                                                ref={searchInputRef}
                                                type="text"
                                                placeholder="Search accounts"
                                                value={credentialSearchQuery}
                                                onChange={(e) => setCredentialSearchQuery(e.target.value)}
                                                className="w-full bg-transparent py-2.5 pl-9 pr-3 text-[13px] text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                                            />
                                        </div>

                                        <div className="max-h-56 overflow-y-auto scrollbar-subtle">
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    handleCredentialSelect(req.credential_type, '');
                                                    setOpenDropdownType(null);
                                                }}
                                                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-muted-foreground transition-colors hover:bg-accent"
                                            >
                                                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', !selectedCredentialId ? 'bg-muted-foreground' : 'bg-transparent')} />
                                                None
                                            </button>

                                            {/* Variable References — filtered by credential type */}
                                            {vars.length > 0 && (<>
                                                <div className="px-3 pb-1 pt-2 text-[12px] text-muted-foreground">Variables</div>
                                                {vars.map((v) => {
                                                    const varRef = `{{vars.${v.name}}}`;
                                                    return (
                                                        <button
                                                            key={varRef}
                                                            type="button"
                                                            onClick={() => {
                                                                handleCredentialSelect(req.credential_type, varRef);
                                                                setOpenDropdownType(null);
                                                            }}
                                                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors hover:bg-accent"
                                                        >
                                                            <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', selectedCredentialId === varRef ? 'bg-emerald-500' : 'bg-transparent')} />
                                                            <span className="text-emerald-600 dark:text-emerald-300">{v.name}</span>
                                                        </button>
                                                    );
                                                })}
                                            </>)}

                                            {filteredCredentials.length > 0 ? (
                                                filteredCredentials.map((cred) => (
                                                    <div key={cred.id} className="flex w-full items-center text-[13px] transition-colors hover:bg-accent">
                                                        <button
                                                            type="button"
                                                            onClick={() => {
                                                                handleCredentialSelect(req.credential_type, cred.id);
                                                                setOpenDropdownType(null);
                                                            }}
                                                            className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left"
                                                        >
                                                            <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', selectedCredentialId === cred.id ? 'bg-foreground' : 'bg-transparent')} />
                                                            <span className={cn('truncate', cred.revoked_at ? 'text-muted-foreground line-through' : isDisconnected(cred) ? 'text-muted-foreground' : 'text-foreground')}>
                                                                {cred.name}
                                                            </span>
                                                            {cred.revoked_at ? (
                                                                <span className="shrink-0 text-[11.5px] text-red-600 dark:text-red-400" title="Disconnected or revoked: connect the account again to use it">
                                                                    Revoked
                                                                </span>
                                                            ) : isDisconnected(cred) ? (
                                                                <span className="shrink-0 text-[11.5px] text-red-600 dark:text-red-400" title="The connection dropped: scan a fresh QR code to link it again">
                                                                    Disconnected
                                                                </span>
                                                            ) : null}
                                                        </button>
                                                        {/* Owner-only controls: hidden for any cred the viewer doesn't own (backend rejects them anyway),
                                                            and in a compact host, a question that offers picking or connecting only. */}
                                                        {!compact && isOwnedByViewer(cred) && (
                                                            <div className="flex items-center gap-0.5 pr-1.5">
                                                                <button
                                                                    type="button"
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        setShareCredential({ id: cred.id, name: cred.name });
                                                                        setOpenDropdownType(null);
                                                                    }}
                                                                    className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                                                    title="Share"
                                                                    aria-label={`Share ${cred.name}`}
                                                                >
                                                                    <Share2 className="h-3.5 w-3.5" />
                                                                </button>
                                                                <button
                                                                    type="button"
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        openDeleteDialog(cred.id, cred.name, req.credential_type);
                                                                        setOpenDropdownType(null);
                                                                    }}
                                                                    className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 dark:hover:text-red-400"
                                                                    title="Delete"
                                                                    aria-label={`Delete ${cred.name}`}
                                                                >
                                                                    <Trash2 className="h-3.5 w-3.5" />
                                                                </button>
                                                            </div>
                                                        )}
                                                    </div>
                                                ))
                                            ) : (
                                                credentialSearchQuery && (
                                                    <div className="px-3 py-2 text-[13px] text-muted-foreground">No match</div>
                                                )
                                            )}
                                        </div>

                                        {/* Connecting another opens the connect flow on this way in, below the picker. */}
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setOpenDropdownType(null);
                                                setConnecting(req.credential_type);
                                            }}
                                            className="flex w-full items-center gap-2 border-t border-border px-3 py-2.5 text-left text-[13px] text-foreground transition-colors hover:bg-accent dark:border-foreground/[0.08]"
                                        >
                                            <Plus className="h-3.5 w-3.5" />
                                            Connect another account
                                        </button>
                                    </div>
                                )}
                            </div>

                            {/* Edit/Share/Delete — only for the viewer's OWN credential (the owner note says why otherwise); a compact
                                host keeps Update alone. */}
                            {selectedCredential && isOwnedByViewer(selectedCredential) && (
                                <div className="flex items-center">
                                    <button type="button" onClick={() => startEditCredential(selectedCredential)} className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground" title="Update" aria-label={`Update ${selectedCredential.name}`}>
                                        <Edit2 className="h-3.5 w-3.5" />
                                    </button>
                                    {!compact && (
                                        <>
                                            <button type="button" onClick={() => setShareCredential({ id: selectedCredential.id, name: selectedCredential.name })} className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground" title="Share" aria-label={`Share ${selectedCredential.name}`}>
                                                <Share2 className="h-3.5 w-3.5" />
                                            </button>
                                            <button type="button" onClick={() => openDeleteDialog(selectedCredential.id, selectedCredential.name, req.credential_type)} className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 dark:hover:text-red-400" title="Delete" aria-label={`Delete ${selectedCredential.name}`}>
                                                <Trash2 className="h-3.5 w-3.5" />
                                            </button>
                                        </>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Why the owner-only controls are absent: a run-as-owner cred (shared into this flow) or one shared
                            with the viewer directly. */}
                        {selectedCredential && !isOwnedByViewer(selectedCredential) && (
                            <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">
                                Owned by <span className="text-foreground">{ownerLabel(selectedCredential)}</span>.{' '}
                                {selectedCredential.owner_name ? 'It’s shared with this flow.' : 'It’s shared with you; remove it from Connections.'}
                            </p>
                        )}

                        {/* Attached-credential health: a revoked (or vanished) credential must say WHY runs will fail. */}
                        {health !== 'ok' && (
                            <p data-testid="credential-health-warning" className="mt-1.5 flex items-start gap-1.5 text-[12.5px] leading-relaxed text-red-600 dark:text-red-400">
                                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                <span>
                                    {health === 'disconnected'
                                        // The provider check ships its own repair guidance (re-scan this WhatsApp credential,
                                        // reinstall the Discord bot); the wire model guarantees one for every dropped verdict.
                                        ? (availableCredentials.find(c => c.id === selectedCredentialId)?.connection_hint ?? 'This connection dropped and nothing is arriving through it. Connect the same account again below.')
                                        : health === 'revoked'
                                            ? 'This account was disconnected or revoked, so runs can’t use it. Connect it again below, or choose another.'
                                            : 'The attached account no longer exists or isn’t yours to use. Connect one below, or choose another.'}
                                </span>
                            </p>
                        )}

                        {/* What connecting proved. A credential created or re-keyed here shows the probe's verdict in full;
                            one connected earlier shows what its row remembers. */}
                        {selectedCredential && selectedCredentialId && (
                            selectedCredentialId in verifications ? (
                                <ConnectionVerdict className="mt-3" verification={verifications[selectedCredentialId]} providerLabel={app} accountLine={selectedCredential.metadata?.email as string | undefined} />
                            ) : (
                                <StoredVerdict className="mt-1.5" metadata={selectedCredential.metadata} />
                            )
                        )}
                    </div>
                );
            })}

            {connectOpen ? (
                <div className={cn(pickers.length > 0 && 'border-t border-border pt-5 dark:border-foreground/[0.08]')}>
                    {pickers.length > 0 && (
                        <div className="mb-4 flex items-center justify-between gap-3">
                            <p className="text-[14.5px] font-medium text-foreground">Connect another account</p>
                            {connecting !== null && (
                                <button type="button" onClick={() => setConnecting(null)} className={INLINE_ACTION}>
                                    Never mind
                                </button>
                            )}
                        </div>
                    )}
                    <AppConnect
                        key={typeof connecting === 'string' ? connecting : qrRepair?.id ?? 'connect'}
                        nodeType={nodeType}
                        app={app}
                        showResult={false}
                        // Compact surfaces (Setup, the ask drawer, the chat's setup card) belong to someone already asking.
                        ask={!compact}
                        initialMethod={typeof connecting === 'string' ? connecting : qrRepair?.credential_type}
                        qrReconnectId={qrRepair?.id}
                        qrAutoStart={!usableNumber || !!qrRepair}
                        onConnected={(credential, verification) => {
                            mintedCredentialIdsRef.current.add(credential.id);
                            handleCredentialSelect(credential.credential_type, credential.id, credential);
                            recordVerification(credential.id, verification);
                            setConnecting(null);
                            void loadCredentials();
                            onConnected?.(credential.id);
                        }}
                    />
                </div>
            ) : (
                <button type="button" onClick={() => setConnecting(true)} className={cn(INLINE_ACTION, 'inline-flex items-center gap-1.5')}>
                    <Plus className="h-3.5 w-3.5" />
                    Connect another account
                </button>
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
        </div>
    );
};
