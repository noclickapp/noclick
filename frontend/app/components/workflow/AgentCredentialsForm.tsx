// AgentCredentialsForm component for AI Agent node credentials.
// Dynamically renders credential fields based on the selected model/provider.
// Implements the CustomCredentialForm interface for use in NodeCredentials.

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
    Eye,
    EyeOff,
    Check,
    AlertCircle,
    ChevronDown,
    ChevronRight,
    Plus,
    X,
    Search,
    Trash2,
    Share2,
    ExternalLink,
} from 'lucide-react';
import { useModels } from '~/hooks/useModels';
import { getProviderMetadata, ModelProvider } from '~/types/provider';
import { sendEventAsync } from '~/lib/socket-sender';
import type { CustomCredentialFormProps } from './NodeCredentials';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { FieldRequirementBadge, isFieldFilled } from './FieldRequirementBadge';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { CredentialRequestActions } from './CredentialRequestActions';
import { AgentOAuthConnect } from './AgentOAuthConnect';
import { AgentEnvVarsSection } from './AgentEnvVarsSection';
import {
    agentAllowsUsageBased,
    getAgentConfigRecord,
    getAgentCredentialIdForProvider,
    getAgentCredentialType,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    inferProviderFromPrefix,
    isChatGptPlusSupported,
    isPrimaryAgentCredentialKey,
    AGENT_ENV_CREDENTIAL_TYPE,
} from '~/lib/agentCredentialModel';
import { isCliAgentModel, cliHarnessBinary } from '~/lib/agentChat';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { isLocalEdition } from '~/lib/edition';

interface Credential {
    id: string;
    name: string;
    credential_type: string;
    metadata?: Record<string, any>;
    created_at: string;
    updated_at: string;
}

// CLI agent providers that support an OAuth/subscription sign-in on the public
// credential-provide page (mirrors harness_oauth_flows.AGENT_PROVIDER_OAUTH_TYPE).
// Lets the request button surface even for OAuth-only providers (no API key).
const AGENT_OAUTH_PROVIDERS = new Set<ModelProvider>([
    ModelProvider.CODEX,
    ModelProvider.CLAUDE_CODE,
]);

/**
 * Get human-readable label for an environment variable name.
 */
function getFieldLabel(envVar: string): string {
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

/**
 * Determine if a field should be masked (password-style input).
 */
function shouldMaskField(envVar: string): boolean {
    const lowerVar = envVar.toLowerCase();
    return (
        lowerVar.includes('key') ||
        lowerVar.includes('secret') ||
        lowerVar.includes('token') ||
        lowerVar.includes('password') ||
        lowerVar.includes('jwt')
    );
}

/**
 * Get placeholder text for a field.
 */
function getPlaceholder(envVar: string): string {
    if (envVar.includes('_API_BASE') || envVar.includes('_URL')) {
        return 'https://...';
    }
    if (envVar.includes('_API_VERSION')) {
        return 'e.g., 2024-02-01';
    }
    if (envVar.includes('_REGION')) {
        return 'e.g., us-east-1';
    }
    if (envVar.includes('_PROJECT')) {
        return 'e.g., my-project-id';
    }
    if (envVar.includes('_LOCATION')) {
        return 'e.g., us-central1';
    }
    return 'Enter value...';
}

export function AgentCredentialsForm({
    nodeData,
    credentialIds,
    onCredentialIdsChange,
    compact,
}: CustomCredentialFormProps) {
    // nodeData is the wrapped { operation, config } shape; getAgentConfigRecord
    // unwraps to the raw config so provider/model changes immediately drive
    // credential requirements. Cast widens the typed shape to the record the
    // helper accepts — safe because the runtime check inside is shape-agnostic.
    const agentConfig = useMemo(
        () => getAgentConfigRecord(nodeData as Record<string, unknown>),
        [nodeData]
    );

    const selectedModel = getAgentSelectedModel(
        typeof agentConfig.model === 'string' ? agentConfig.model : undefined,
        agentConfig
    );
    // For wrapper runtimes like hermes and openclaw, the credential type is
    // determined by the underlying provider/model field so users can reuse their
    // existing provider credentials (e.g. agent_openrouter).
    const effectiveModel = getAgentEffectiveModel(
        typeof agentConfig.model === 'string' ? agentConfig.model : undefined,
        agentConfig
    );

    // Track which fields have their values shown (for password toggle)
    const [visibleFields, setVisibleFields] = useState<Set<string>>(new Set());

    // Saved credentials state
    const [savedCredentials, setSavedCredentials] = useState<Credential[]>([]);
    const [loadingCredentials, setLoadingCredentials] = useState(true);

    // Dropdown state
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    // Advanced disclosure (sandbox env vars). Starts open when a bundle is already
    // linked OR the builder has REQUESTED env vars — so neither existing config nor
    // a pending request is hidden behind a collapsed section.
    const [showAdvanced, setShowAdvanced] = useState(
        () =>
            Boolean(credentialIds?.[AGENT_ENV_CREDENTIAL_TYPE]) ||
            (Array.isArray(agentConfig.agent_env_requested) &&
                agentConfig.agent_env_requested.length > 0)
    );
    const [searchQuery, setSearchQuery] = useState('');
    const dropdownRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    // Delete confirmation state
    const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
    const [credentialToDelete, setCredentialToDelete] = useState<{
        id: string;
        name: string;
    } | null>(null);

    // Share dialog state
    const [shareCredential, setShareCredential] = useState<{
        id: string;
        name: string;
    } | null>(null);

    // Create new credential state
    const [isCreating, setIsCreating] = useState(false);
    const [newCredentialName, setNewCredentialName] = useState('');
    const [newCredentialData, setNewCredentialData] = useState<
        Record<string, string>
    >({});
    const [createLoading, setCreateLoading] = useState(false);
    const [createError, setCreateError] = useState<string | null>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);

    // Use the models hook to look up the model and get its provider
    const { getModelById } = useModels();

    // Get the model and its provider metadata.
    // effectiveModel is used so hermes routes credential UI to the underlying provider
    // (e.g. openrouter) rather than the generic hermes_agent provider.
    const { provider, providerMetadata, providerTitle } = useMemo(() => {
        const model = getModelById(effectiveModel);
        if (model) {
            const metadata = getProviderMetadata(model.provider);
            return {
                provider: model.provider,
                providerMetadata: metadata,
                providerTitle: metadata?.title || model.provider,
            };
        }
        // Fallback: infer provider from model ID prefix for dynamic models not in the catalog
        const inferred = inferProviderFromPrefix(effectiveModel);
        if (inferred) {
            const metadata = getProviderMetadata(inferred);
            return {
                provider: inferred,
                providerMetadata: metadata,
                providerTitle: metadata?.title || String(inferred),
            };
        }
        return {
            provider: null,
            providerMetadata: undefined,
            providerTitle: effectiveModel,
        };
    }, [effectiveModel, getModelById]);

    const credentialType = provider ? getAgentCredentialType(provider) : null;
    const requiredKeys = providerMetadata?.requiredApiKeys?.[0] || [];
    const allowUsageBased = agentAllowsUsageBased(selectedModel, provider);
    const selectedCredentialId = getAgentCredentialIdForProvider(
        credentialIds,
        provider
    );

    // Which agent OAuth sign-in (if any) applies to the selected model. The
    // provider→component mapping lives in AgentOAuthConnect; here we only decide
    // WHICH credential type applies, gated by wrapper/subscription eligibility:
    //  - Codex: standalone CODEX, or OPENAI inside a CLI wrapper whose sub-model is
    //    ChatGPT-Plus-eligible (agent_codex_oauth is interchangeable with codex CLI).
    //  - Claude Code: standalone CLAUDE_CODE, or ANTHROPIC inside any CLI wrapper.
    const oauthCredentialType = useMemo<string | null>(() => {
        // These sign-ins hand NoClick a subscription token to run in a hosted
        // sandbox. Self-hosted runs the operator's OWN installed CLI, already
        // authenticated by them, and the OAuth handlers don't ship — so offering
        // "Connect ChatGPT" here would be an option that cannot complete.
        if (isLocalEdition()) return null;
        if (
            provider === ModelProvider.CODEX ||
            (provider === ModelProvider.OPENAI &&
                isCliAgentModel(selectedModel) &&
                (!effectiveModel.startsWith('openai/') ||
                    isChatGptPlusSupported(effectiveModel.slice('openai/'.length))))
        ) {
            return 'agent_codex_oauth';
        }
        if (
            provider === ModelProvider.CLAUDE_CODE ||
            (provider === ModelProvider.ANTHROPIC && isCliAgentModel(selectedModel))
        ) {
            return 'agent_claude_code_oauth';
        }
        return null;
    }, [provider, selectedModel, effectiveModel]);

    // Load saved credentials
    const loadCredentials = useCallback(async () => {
        try {
            setLoadingCredentials(true);
            const response = await sendEventAsync({
                event_name: 'credential:list',
                request_id: `list-agent-creds-${Date.now()}`,
            });
            if (response?.credentials) {
                setSavedCredentials(response.credentials);
            }
        } catch (err) {
            console.error(
                '[AgentCredentialsForm] Error loading credentials:',
                err
            );
        } finally {
            setLoadingCredentials(false);
        }
    }, []);

    useEffect(() => {
        loadCredentials();
    }, [loadCredentials]);

    // Filter credentials by provider (include both API key and OAuth
    // types for agent CLIs and for the OpenCode wrapper context where
    // anthropic/* / openai/* sub-models can also use Claude Pro / ChatGPT
    // Plus OAuth credentials interchangeably).
    const matchingCredentials = useMemo(() => {
        if (!credentialType) return [];
        // Map of providers → extra OAuth credential types to fold in.
        // The credential is interchangeable from the user's perspective
        // (same underlying account, same upstream service); the form
        // surfaces them in one dropdown so users don't get confused
        // about which credential applies.
        //
        // OPENAI's alias is gated below — opencode-ai's CodexAuthPlugin
        // only accepts a Codex CLI subset over ChatGPT Plus OAuth, so
        // we hide the Codex OAuth option for openai/* sub-models that
        // aren't in the daily-refreshed list. Without this, the form
        // would let the user pick OAuth for openai/gpt-4.1 and the run
        // would fail at sandbox launch with an actionable but late
        // error.
        const oauthAliases: Partial<Record<ModelProvider, string[]>> = {
            [ModelProvider.CODEX]: ['agent_codex_oauth'],
            [ModelProvider.CLAUDE_CODE]: ['agent_claude_code_oauth'],
            // OpenCode accepts the shared ChatGPT and Claude subscription
            // credentials for eligible OpenAI/Anthropic sub-models.
            [ModelProvider.OPENAI]: [],
            [ModelProvider.ANTHROPIC]: ['agent_claude_code_oauth'],
        };

        // ChatGPT Plus OAuth eligibility for OPENAI: gate by the
        // daily-refreshed Codex CLI model list (see isChatGptPlusSupported).
        // For wrapper context (`openai/<bare>`), strip the prefix and
        // check the bare id; for the standalone OPENAI credential
        // (no wrapper sub-model — effectiveModel won't start with
        // `openai/`), allow the alias since the user is configuring
        // a direct OpenAI agent without a prefix gate.
        if (provider === ModelProvider.OPENAI) {
            if (effectiveModel.startsWith('openai/')) {
                const bare = effectiveModel.slice('openai/'.length);
                if (isChatGptPlusSupported(bare)) {
                    oauthAliases[ModelProvider.OPENAI] = ['agent_codex_oauth'];
                }
                // else: leave [] — Codex OAuth credentials hidden from the
                // form so the user can't pick an unsupported combination.
            } else {
                // Non-wrapper context: keep the alias enabled so direct
                // OpenAI agents still surface Codex OAuth credentials.
                oauthAliases[ModelProvider.OPENAI] = ['agent_codex_oauth'];
            }
        }

        const acceptedTypes = new Set<string>([credentialType]);
        for (const t of oauthAliases[provider as ModelProvider] || []) {
            acceptedTypes.add(t);
        }
        return savedCredentials.filter((cred) =>
            acceptedTypes.has(cred.credential_type)
        );
    }, [savedCredentials, credentialType, provider, effectiveModel]);

    // Filter by search query
    const filteredCredentials = useMemo(
        () =>
            fuzzyFilter(matchingCredentials, searchQuery, (cred) => [
                { text: cred.name.toLowerCase(), weight: 1, fuzzy: true },
            ]),
        [matchingCredentials, searchQuery]
    );

    // Get selected credential
    const selectedCredential = useMemo(() => {
        return matchingCredentials.find((c) => c.id === selectedCredentialId);
    }, [matchingCredentials, selectedCredentialId]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                dropdownRef.current &&
                !dropdownRef.current.contains(event.target as Node)
            ) {
                setIsDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () =>
            document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Focus search input when dropdown opens
    useEffect(() => {
        if (isDropdownOpen && searchInputRef.current) {
            searchInputRef.current.focus();
        }
    }, [isDropdownOpen]);

    // Clear search when dropdown closes
    useEffect(() => {
        if (!isDropdownOpen) {
            setSearchQuery('');
        }
    }, [isDropdownOpen]);

    // Handle credential selection from dropdown
    const handleSelectCredential = useCallback(
        (credentialId: string | null) => {
            // Build new credentialIds, removing any existing agent_* keys
            const newCredentialIds = { ...credentialIds };
            Object.keys(newCredentialIds).forEach((key) => {
                if (isPrimaryAgentCredentialKey(key)) delete newCredentialIds[key];
            });

            // Add new selection if provided
            if (credentialId && credentialType) {
                newCredentialIds[credentialType] = credentialId;
            }

            onCredentialIdsChange(newCredentialIds);
            setIsDropdownOpen(false);
        },
        [credentialIds, credentialType, onCredentialIdsChange]
    );

    // Toggle visibility of a field
    const toggleVisibility = useCallback((field: string) => {
        setVisibleFields((prev) => {
            const next = new Set(prev);
            if (next.has(field)) {
                next.delete(field);
            } else {
                next.add(field);
            }
            return next;
        });
    }, []);

    // Handle new credential field change
    const handleNewCredentialFieldChange = useCallback(
        (field: string, value: string) => {
            setNewCredentialData((prev) => {
                const next = { ...prev };
                if (value.trim()) {
                    next[field] = value;
                } else {
                    delete next[field];
                }
                return next;
            });
        },
        []
    );

    // Create new credential
    const handleCreateCredential = useCallback(async () => {
        if (!credentialType) return;

        setCreateError(null);
        setCreateLoading(true);

        try {
            const response = await sendEventAsync({
                event_name: 'credential:create',
                request_id: `create-agent-cred-${Date.now()}`,
                name:
                    newCredentialName ||
                    `${providerTitle} - ${new Date().toLocaleDateString()}`,
                credential_type: credentialType,
                credential_data: { credentials: newCredentialData },
                metadata: { provider: provider },
            });

            if (response?.success && response.credential) {
                await loadCredentials();
                handleSelectCredential(response.credential.id);
                setIsCreating(false);
                setNewCredentialName('');
                setNewCredentialData({});
            } else {
                const errMsg =
                    response?.error ||
                    response?.message ||
                    'Failed to create credential';
                if (isPlanLimitError(errMsg)) {
                    setPlanLimitError(errMsg);
                } else {
                    setCreateError(errMsg);
                }
            }
        } catch (err) {
            console.error(
                '[AgentCredentialsForm] Error creating credential:',
                err
            );
            const errMsg =
                err instanceof Error
                    ? err.message
                    : 'Failed to create credential';
            if (isPlanLimitError(errMsg)) {
                setPlanLimitError(errMsg);
            } else {
                setCreateError(errMsg);
            }
        } finally {
            setCreateLoading(false);
        }
    }, [
        credentialType,
        newCredentialName,
        newCredentialData,
        providerTitle,
        provider,
        loadCredentials,
        handleSelectCredential,
    ]);

    // Cancel creating
    const cancelCreate = useCallback(() => {
        setIsCreating(false);
        setNewCredentialName('');
        setNewCredentialData({});
        setCreateError(null);
    }, []);

    // Open delete confirmation dialog
    const openDeleteDialog = useCallback(
        (credentialId: string, credentialName: string) => {
            setCredentialToDelete({ id: credentialId, name: credentialName });
            setIsDeleteDialogOpen(true);
            setIsDropdownOpen(false);
        },
        []
    );

    // Confirm and execute deletion
    const confirmDeleteCredential = useCallback(async () => {
        if (!credentialToDelete) return;
        try {
            const response = await sendEventAsync({
                event_name: 'credential:delete',
                request_id: `delete-agent-cred-${Date.now()}`,
                credential_id: credentialToDelete.id,
                confirm: true,
            });
            if (response?.success) {
                await loadCredentials();
                // Clear selection if the deleted credential was selected
                if (selectedCredentialId === credentialToDelete.id) {
                    handleSelectCredential(null);
                }
            } else {
                alert(response?.message || 'Failed to delete credential');
            }
        } catch (err) {
            console.error(
                '[AgentCredentialsForm] Error deleting credential:',
                err
            );
            alert('Failed to delete credential');
        } finally {
            setCredentialToDelete(null);
        }
    }, [
        credentialToDelete,
        loadCredentials,
        selectedCredentialId,
        handleSelectCredential,
    ]);

    // Check if required fields are filled (for create mode).
    //
    // The multi-provider CLI wrappers (OpenCode, OpenClaw, Hermes) all now
    // show exactly one field at a time — the bare wrapper defaults to a
    // single recommended provider key, and picking a sub-model switches
    // the field via inferProviderFromPrefix. So `every` and `some`
    // produce the same answer in practice. We keep `some` for those
    // wrappers as defence-in-depth: if a future change re-introduces
    // multiple alternative fields for them, the "any one is sufficient"
    // semantics should still apply (they're "OR" wrappers — the user
    // only needs one upstream credential to run any model).
    const allNewRequiredFilled = useMemo(() => {
        const multiAlternativeWrappers = new Set<ModelProvider>([
            ModelProvider.OPENCODE,
            ModelProvider.OPENCLAW,
            ModelProvider.HERMES_AGENT,
        ]);
        if (provider && multiAlternativeWrappers.has(provider)) {
            return requiredKeys.some((key) => newCredentialData[key]?.trim());
        }
        return requiredKeys.every((key) => newCredentialData[key]?.trim());
    }, [requiredKeys, newCredentialData, provider]);

    // If no metadata found, show a message
    if (!providerMetadata) {
        return (
            <div className="text-sm text-muted-foreground dark:text-zinc-500">
                <p>Provider metadata not found for model.</p>
                <p className="text-xs mt-1">Model ID: {selectedModel}</p>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            {/* Provider Info Header — title + a deep link to the provider's
                API-key dashboard. Styling matches NodeCredentials.tsx's
                `x-credential-url` rendering so the agent form looks visually
                consistent with every other node's credential form (blue
                link, "Get your API key here", on its own line below the
                title). providerURL is provider-scoped; since the form shows
                one provider's fields at a time (driven by the selected
                model and its sub-model), a single link is the right target. */}
            <div className="space-y-1">
                <h3 className="text-sm font-medium text-foreground">
                    {providerTitle} Credentials
                </h3>
                {providerMetadata?.providerURL && (
                    <a
                        href={providerMetadata.providerURL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-500 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
                    >
                        Get your API key here
                        <ExternalLink className="w-3 h-3" />
                    </a>
                )}
                {allowUsageBased && (
                    <p className="text-xs text-green-600 dark:text-green-400">
                        ✓ Usage-based billing available - credentials optional
                    </p>
                )}
                {!allowUsageBased && (
                    /* BYOK harnesses bill the provider's prepaid balance, which
                       is separate from the platform credit balance. */
                    <p className="text-[11px] text-zinc-600">
                        API keys use your {providerTitle} account&apos;s prepaid credits —
                        separate from your NoClick credit balance.
                    </p>
                )}
            </div>

            {/* Credential Selection Dropdown */}
            {matchingCredentials.length > 0 && !isCreating && (
                <div className="flex items-center gap-1">
                    <div className="relative flex-1 min-w-0" ref={dropdownRef}>
                        <button
                            type="button"
                            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                            className="w-full px-3 py-2 text-sm bg-card dark:bg-card/50 border border-border rounded-lg text-left flex items-center justify-between hover:bg-accent dark:hover:bg-card hover:border-foreground/20 transition-all group"
                        >
                            <span
                                className={`truncate ${selectedCredential ? 'text-foreground/80' : 'text-muted-foreground dark:text-zinc-500'}`}
                            >
                                {selectedCredential
                                    ? selectedCredential.name
                                    : 'Select saved credential...'}
                            </span>
                            <ChevronDown
                                className={`h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/70 transition-all flex-shrink-0 ml-2 ${
                                    isDropdownOpen ? 'rotate-180' : ''
                                }`}
                            />
                        </button>

                        {isDropdownOpen && (
                            <div className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-2xl overflow-hidden animate-fade-in">
                                {/* Search Input */}
                                <div className="relative border-b border-border">
                                    <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                                    <input
                                        ref={searchInputRef}
                                        type="text"
                                        placeholder="Search..."
                                        value={searchQuery}
                                        onChange={(e) =>
                                            setSearchQuery(e.target.value)
                                        }
                                        className="w-full pl-8 pr-2.5 py-2 bg-transparent text-foreground/80 placeholder:text-[hsl(var(--placeholder))] text-xs focus:outline-none"
                                    />
                                </div>

                                <div className="max-h-48 overflow-y-auto scrollbar-subtle">
                                    {/* None Option */}
                                    <button
                                        type="button"
                                        onClick={() =>
                                            handleSelectCredential(null)
                                        }
                                        className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center justify-between"
                                    >
                                        <span className="text-muted-foreground dark:text-zinc-500 italic">
                                            {allowUsageBased
                                                ? 'Use NoClick billing'
                                                : 'None selected'}
                                        </span>
                                        {!selectedCredentialId && (
                                            <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground dark:bg-zinc-500" />
                                        )}
                                    </button>

                                    {/* Credential Options */}
                                    {filteredCredentials.map((cred) => (
                                        <div
                                            key={cred.id}
                                            className="flex items-center border-t border-border/30 dark:border-zinc-800/30 hover:bg-accent transition-colors group"
                                        >
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    handleSelectCredential(
                                                        cred.id
                                                    )
                                                }
                                                className="flex-1 px-3 py-2 text-xs text-left flex items-center justify-between min-w-0"
                                            >
                                                <span className="text-foreground/80 truncate">
                                                    {cred.name}
                                                </span>
                                                {selectedCredentialId ===
                                                    cred.id && (
                                                    <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground flex-shrink-0 ml-2" />
                                                )}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    openDeleteDialog(
                                                        cred.id,
                                                        cred.name
                                                    );
                                                }}
                                                className="p-2 opacity-0 group-hover:opacity-100 hover:text-red-600 dark:hover:text-red-400 text-muted-foreground dark:text-zinc-500 transition-all flex-shrink-0"
                                                title="Delete credential"
                                            >
                                                <Trash2 className="h-3 w-3" />
                                            </button>
                                        </div>
                                    ))}

                                    {filteredCredentials.length === 0 &&
                                        searchQuery && (
                                            <div className="px-3 py-2 text-xs text-muted-foreground/70 dark:text-zinc-600 italic border-t border-border/30 dark:border-zinc-800/30">
                                                No matching credentials
                                            </div>
                                        )}
                                </div>
                            </div>
                        )}
                    </div>
                    {/* Share/Delete Actions - show when a credential is selected */}
                    {selectedCredential && (
                        <div className="flex items-center gap-0.5">
                            <button
                                onClick={() =>
                                    setShareCredential({
                                        id: selectedCredential.id,
                                        name: selectedCredential.name,
                                    })
                                }
                                className="p-2 hover:bg-accent rounded-lg transition-colors"
                                title="Share credential"
                            >
                                <Share2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 hover:text-blue-600 dark:hover:text-blue-400" />
                            </button>
                            <button
                                onClick={() =>
                                    openDeleteDialog(
                                        selectedCredential.id,
                                        selectedCredential.name
                                    )
                                }
                                className="p-2 hover:bg-accent rounded-lg transition-colors"
                                title="Delete credential"
                            >
                                <Trash2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 hover:text-red-600 dark:hover:text-red-400" />
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Create New Credential Form */}
            {isCreating ? (
                <div className="p-4 rounded-lg bg-card/50 border border-border space-y-3">
                    <div className="flex items-center justify-between mb-2">
                        <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                            New {providerTitle} Credential
                        </div>
                        <button
                            onClick={cancelCreate}
                            className="p-1 hover:bg-accent rounded transition-colors"
                        >
                            <X className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
                        </button>
                    </div>

                    {/* Credential Name */}
                    <div className="space-y-1.5">
                        <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                            Name
                            <FieldRequirementBadge isRequired={false} />
                        </label>
                        <input
                            type="text"
                            value={newCredentialName}
                            onChange={(e) =>
                                setNewCredentialName(e.target.value)
                            }
                            placeholder={`My ${providerTitle} API Key`}
                            className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors"
                        />
                    </div>

                    {/* Credential Fields */}
                    {requiredKeys.map((envVar) => {
                        const isVisible = visibleFields.has(`new_${envVar}`);
                        const isMasked = shouldMaskField(envVar);
                        const value = newCredentialData[envVar] || '';

                        return (
                            <div key={envVar} className="space-y-1.5">
                                <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                                    {getFieldLabel(envVar)}
                                    <FieldRequirementBadge isRequired isFilled={isFieldFilled(value)} />
                                </label>
                                <div className="relative">
                                    <input
                                        type={
                                            isMasked && !isVisible
                                                ? 'password'
                                                : 'text'
                                        }
                                        value={value}
                                        onChange={(e) =>
                                            handleNewCredentialFieldChange(
                                                envVar,
                                                e.target.value
                                            )
                                        }
                                        placeholder={getPlaceholder(envVar)}
                                        className="w-full px-3 py-2 pr-10 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors font-mono"
                                    />
                                    {isMasked && (
                                        <button
                                            type="button"
                                            onClick={() =>
                                                toggleVisibility(
                                                    `new_${envVar}`
                                                )
                                            }
                                            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors"
                                        >
                                            {isVisible ? (
                                                <EyeOff className="h-4 w-4" />
                                            ) : (
                                                <Eye className="h-4 w-4" />
                                            )}
                                        </button>
                                    )}
                                </div>
                            </div>
                        );
                    })}

                    {createError && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                            {/* pre-line: validation rejections separate guidance from the
                                provider's verbatim detail with a blank line — keep it. */}
                            <div className="text-xs text-red-500 whitespace-pre-line break-words">
                                {createError}
                            </div>
                        </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2 pt-1">
                        <button
                            onClick={cancelCreate}
                            className="flex-1 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleCreateCredential}
                            disabled={createLoading || !allNewRequiredFilled}
                            className="flex-1 px-3 py-2 text-xs text-primary-foreground dark:text-foreground bg-primary dark:bg-zinc-700 hover:bg-primary/90 dark:hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-transparent dark:border-zinc-700 dark:hover:border-zinc-600 disabled:border-border rounded-lg transition-all flex items-center justify-center gap-1.5"
                        >
                            {createLoading ? (
                                'Creating...'
                            ) : (
                                <>
                                    <Check className="h-3 w-3" /> Save
                                </>
                            )}
                        </button>
                    </div>
                </div>
            ) : (
                    <button
                        onClick={() => setIsCreating(true)}
                        className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 bg-card dark:bg-card/50 hover:bg-accent dark:hover:bg-card border border-border hover:border-foreground/20 rounded-lg transition-all"
                    >
                        <Plus className="h-3.5 w-3.5" />
                        {provider === ModelProvider.CODEX ||
                        provider === ModelProvider.CLAUDE_CODE ||
                        provider === ModelProvider.OPENCODE ||
                        provider === ModelProvider.OPENCLAW ||
                        provider === ModelProvider.HERMES_AGENT ||
                        provider === ModelProvider.XAI
                            ? 'Connect with API key'
                            : 'Create new credential'}
                    </button>
            )}

            {/* Agent CLI subscription sign-in (ChatGPT / Claude). Rendered through
                the shared AgentOAuthConnect — the same entry
                point the public credential-provide page uses — so the flow can't
                diverge between the two surfaces. Which provider applies is decided by
                `oauthCredentialType` above; the provider→component mapping lives in
                AgentOAuthConnect. */}
            {!isCreating && oauthCredentialType && (
                <AgentOAuthConnect
                    credentialType={oauthCredentialType}
                    credentialIds={credentialIds}
                    onCredentialIdsChange={onCredentialIdsChange}
                    onCredentialCreated={loadCredentials}
                />
            )}

            {/* Self-hosted CLI harnesses authenticate outside the app entirely. */}
            {isLocalEdition() && isCliAgentModel(selectedModel) && (
                <div className="text-xs text-muted-foreground dark:text-zinc-500 bg-card dark:bg-zinc-800/30 border border-border/60 dark:border-transparent rounded-lg px-3 py-2">
                    Runs your locally installed <code>{cliHarnessBinary(selectedModel)}</code> CLI
                    and uses whatever account it is already signed in to. Sign in from your
                    terminal (for example <code>{cliHarnessBinary(selectedModel)} login</code>);
                    no credential is needed here.
                </div>
            )}

            {/* Usage-based billing note (when no credential selected and not creating) */}
            {allowUsageBased && !selectedCredentialId && !isCreating && (
                <div className="text-xs text-muted-foreground dark:text-zinc-500 bg-card dark:bg-zinc-800/30 border border-border/60 dark:border-transparent rounded-lg px-3 py-2">
                    Using NoClick's usage-based billing (no credentials needed)
                </div>
            )}

            {/* Warning for providers that require credentials */}
            {!allowUsageBased &&
                !selectedCredentialId &&
                !isCreating &&
                matchingCredentials.length === 0 && (
                    <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                        <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
                        <span>
                            This provider requires credentials. Create one
                            above.
                        </span>
                    </div>
                )}

            {/* Ask someone else to provide this credential (via email or a copy-able
                link). Shown for API-key providers and the OAuth CLI agents shipped
                in this edition (Codex and Claude Code). */}
            {!compact && credentialType && !isCreating &&
                (requiredKeys.length > 0 || (!!provider && AGENT_OAUTH_PROVIDERS.has(provider))) && (
                <CredentialRequestActions credentialType={credentialType} />
            )}

            {/* Advanced: sandbox environment variables — a SECONDARY credential
                (agent_env) in the same credentialIds map, unrelated to the model
                credential. Kept LAST so it never separates the model-credential
                picker from its provider and request-from-teammate notes.
                Collapsed by default; auto-expanded when one is already linked so
                existing config stays discoverable. Hidden while creating a model
                credential so the two forms can't be confused. */}
            {!isCreating && (
                <div className="pt-1">
                    <button
                        type="button"
                        aria-expanded={showAdvanced}
                        onClick={() => setShowAdvanced((v) => !v)}
                        className="flex items-center gap-1 py-1.5 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors"
                    >
                        <ChevronRight
                            className={`h-3 w-3 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
                        />
                        Advanced
                    </button>
                    {showAdvanced && (
                        <div className="space-y-1.5 pb-1">
                            <div className="text-xs text-muted-foreground dark:text-zinc-500">
                                Environment variables
                            </div>
                            <AgentEnvVarsSection
                                credentialIds={credentialIds}
                                onCredentialIdsChange={onCredentialIdsChange}
                                requestedEnvVars={
                                    Array.isArray(agentConfig.agent_env_requested)
                                        ? (agentConfig.agent_env_requested as unknown[])
                                        : undefined
                                }
                            />
                            {/* Do NOT claim the model can't see the values: they live
                                in its shell, so any command can print them. Only the
                                prompt is names-only. Scoping the key is the real
                                containment — same stance as the sandbox git token. */}
                            <div className="text-[11px] text-muted-foreground/80 dark:text-zinc-600">
                                Available in the agent&apos;s sandbox shell (e.g.
                                $STRIPE_KEY) so it can call APIs directly. Values
                                aren&apos;t written into the prompt, but the agent can
                                read them by running a command — scope these keys
                                accordingly.
                            </div>
                        </div>
                    )}
                </div>
            )}

            <DeleteConfirmPopup
                itemType="Credential"
                itemName={credentialToDelete?.name}
                isOpen={isDeleteDialogOpen}
                onOpenChange={setIsDeleteDialogOpen}
                onConfirmDelete={confirmDeleteCredential}
            />
            <ShareDialog
                isOpen={!!shareCredential}
                onOpenChange={(open) => {
                    if (!open) setShareCredential(null);
                }}
                resource={shareCredential}
                resourceType="credential"
            />
            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => {
                    if (!open) setPlanLimitError(null);
                }}
                errorMessage={planLimitError || ''}
            />
        </div>
    );
}
