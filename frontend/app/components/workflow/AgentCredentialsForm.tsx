// The agent node's account for its model: which of your accounts it runs as (a picker, once you have one that runs
// it), what connecting it proved, and connecting another through the flow Connections' AI dialog uses (AiConnect: the
// harness's subscription sign-in where it takes one, then the provider's API key as get-it-then-paste-it steps).
// Implements the CustomCredentialForm interface for NodeCredentials; the sandbox's environment variables sit under
// Advanced, shown in a compact host (the builder's asks, Setup, the chat's cards) only once there are some.

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, Plus, Search, Trash2, Share2 } from 'lucide-react';
import { useModels } from '~/hooks/useModels';
import { getProviderMetadata, ModelProvider } from '~/types/provider';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { sendEventAsync } from '~/lib/socket-sender';
import { cn } from '~/lib/utils';
import type { CustomCredentialFormProps } from './NodeCredentials';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { ConnectionVerdict, StoredVerdict } from '~/components/credential/ConnectionVerdict';
import { AiConnect, agentKeyMethod, agentSignInMethod } from '~/components/shell/connections/AiConnect';
import { FIELD_LABEL } from '~/components/shell/fields';
import { INLINE_ACTION } from './CredentialRequestActions';
import { AgentEnvVarsSection } from './AgentEnvVarsSection';
import { hasAgentOAuthConnect } from './AgentOAuthConnect';
import {
    agentAllowsUsageBased,
    agentVendorKeyAlias,
    claudePlanRefusal,
    getAgentConfigRecord,
    getAgentCredentialIdForProvider,
    getAgentCredentialType,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    inferProviderFromPrefix,
    isChatGptPlusSupported,
    isPrimaryAgentCredentialKey,
    isSignInOnlyAgentProvider,
    sameAccountAgentProviders,
    AGENT_ENV_CREDENTIAL_TYPE,
} from '~/lib/agentCredentialModel';
import { isCliAgentModel, cliHarnessBinary } from '~/lib/agentChat';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { isLocalEdition } from '~/lib/edition';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';

interface Credential {
    id: string;
    name: string;
    credential_type: string;
    metadata?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

export function AgentCredentialsForm({
    nodeData,
    credentialIds,
    onCredentialIdsChange,
    compact,
    onConnected,
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

    // Saved credentials state
    const [savedCredentials, setSavedCredentials] = useState<Credential[]>([]);
    const [loadingCredentials, setLoadingCredentials] = useState(true);

    // Dropdown state
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    // Advanced (sandbox env vars) starts open when a bundle is already linked OR the builder has REQUESTED env vars,
    // so neither existing config nor a pending request hides behind a collapsed section; a compact host shows it only
    // then.
    const envInUse =
        Boolean(credentialIds?.[AGENT_ENV_CREDENTIAL_TYPE]) ||
        (Array.isArray(agentConfig.agent_env_requested) && agentConfig.agent_env_requested.length > 0);
    const [showAdvanced, setShowAdvanced] = useState(envInUse);
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

    // The connect flow, open on asking (closed once an account runs the model), and what connecting a key proved.
    const [connecting, setConnecting] = useState(false);
    const [verifications, setVerifications] = useState<Record<string, CredentialTestConnectionResponse | null>>({});

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
    const planRefusal = claudePlanRefusal(credentialIds, provider);

    // Which agent OAuth sign-in (if any) applies to the selected model. The
    // provider→component mapping lives in AgentOAuthConnect; here we only decide
    // WHICH credential type applies, gated by wrapper/subscription eligibility:
    //  - Codex: standalone CODEX, or OPENAI inside a CLI wrapper whose sub-model is
    //    ChatGPT-Plus-eligible (agent_codex_oauth is interchangeable with codex CLI).
    //  - Claude Code: CLAUDE_CODE only; a Claude plan runs in no other harness.
    //  - GitHub Copilot / xAI: their respective providers, where this instance
    //    offers the sign-in (the backend reports which flows can complete).
    const { agentSignIns } = useInstanceCapabilities();
    const oauthCredentialType = useMemo<string | null>(() => {
        const offered = (key: string) => key in agentSignIns;
        if (
            provider === ModelProvider.CODEX ||
            (provider === ModelProvider.OPENAI &&
                isCliAgentModel(selectedModel) &&
                (!effectiveModel.startsWith('openai/') ||
                    isChatGptPlusSupported(effectiveModel.slice('openai/'.length))))
        ) {
            return offered('codex') ? 'agent_codex_oauth' : null;
        }
        if (provider === ModelProvider.CLAUDE_CODE) {
            return offered('claude_code') ? 'agent_claude_code_oauth' : null;
        }
        if (provider === ModelProvider.GITHUB_COPILOT && offered('github_copilot')) {
            return 'agent_github_copilot_oauth';
        }
        if (provider === ModelProvider.XAI && offered('xai')) return 'agent_xai_oauth';
        return null;
    }, [provider, selectedModel, effectiveModel, agentSignIns]);

    // The ways in: the sign-in first, where the harness takes one, then the provider's own key.
    const methods = useMemo(
        () => [
            ...(oauthCredentialType && hasAgentOAuthConnect(oauthCredentialType) ? [agentSignInMethod(oauthCredentialType)] : []),
            ...(provider && requiredKeys.length > 0 && !isSignInOnlyAgentProvider(provider) ? [agentKeyMethod(provider)] : []),
        ],
        [oauthCredentialType, provider, requiredKeys.length]
    );

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
    // types for agent CLIs and for the wrapper context where openai/* /
    // xai/* sub-models can also use ChatGPT Plus / SuperGrok OAuth
    // credentials interchangeably).
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
            [ModelProvider.GITHUB_COPILOT]: ['agent_github_copilot_oauth'],
            // Wrapper subscription-OAuth aliases: an existing ChatGPT /
            // xAI sign-in is valid for the matching openai/* / xai/*
            // sub-model too. Never a Claude plan (Claude Code only).
            [ModelProvider.OPENAI]: [],
            [ModelProvider.XAI]: ['agent_xai_oauth'],
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
        const vendorKey = agentVendorKeyAlias(provider as ModelProvider);
        if (vendorKey) acceptedTypes.add(vendorKey);
        for (const t of oauthAliases[provider as ModelProvider] || []) {
            acceptedTypes.add(t);
        }
        // A key saved for a provider that shares this one's account holds the same secret.
        for (const other of sameAccountAgentProviders(provider)) {
            acceptedTypes.add(getAgentCredentialType(other));
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

    // A compact host (an ask, Setup) takes an account that already runs the model, so the person confirms rather
    // than hunting for the picker; once per mount, since the host echoes the selection back.
    const autoSelected = useRef(false);
    useEffect(() => {
        if (!compact || autoSelected.current || selectedCredentialId || !credentialType || matchingCredentials.length === 0) return;
        autoSelected.current = true;
        handleSelectCredential(matchingCredentials[0].id);
    }, [compact, selectedCredentialId, credentialType, matchingCredentials, handleSelectCredential]);

    // A sign-in attaches itself (replacing the node's other model accounts); a key is attached here, with its proof.
    const signedIn = useCallback(async () => {
        await loadCredentials();
    }, [loadCredentials]);
    const attachSignIn = useCallback(
        (ids: Record<string, string>) => {
            onCredentialIdsChange(ids);
            setConnecting(false);
            const signedInAs = getAgentCredentialIdForProvider(ids, provider);
            if (signedInAs) onConnected?.(signedInAs);
        },
        [onCredentialIdsChange, provider, onConnected]
    );
    const keySaved = useCallback(
        async (credential: { id: string }, verification: CredentialTestConnectionResponse | null) => {
            await loadCredentials();
            handleSelectCredential(credential.id);
            setVerifications((prev) => ({ ...prev, [credential.id]: verification }));
            setConnecting(false);
            onConnected?.(credential.id);
        },
        [loadCredentials, handleSelectCredential, onConnected]
    );

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

    // If no metadata found, show a message
    if (!providerMetadata) {
        return (
            <div className="text-sm text-muted-foreground dark:text-zinc-500">
                <p>Provider metadata not found for model.</p>
                <p className="text-xs mt-1">Model ID: {selectedModel}</p>
            </div>
        );
    }

    // Until the accounts are read, the flow would open as if there were none.
    if (loadingCredentials && savedCredentials.length === 0) {
        return <div className="py-6 text-center text-[13px] text-muted-foreground">Loading your accounts…</div>;
    }

    const connectOpen = connecting || matchingCredentials.length === 0;

    return (
        // A form's measure, not the panel's, as every account panel has it.
        <div className="max-w-xl space-y-5" data-testid="agent-credentials">
            {/* A Claude plan attached to an anthropic/* model on another harness: why it no longer counts, in the
                backend's words. */}
            {planRefusal && (
                <p role="alert" className="flex items-start gap-2 text-[13px] leading-relaxed text-amber-600 dark:text-amber-400">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    {planRefusal}
                </p>
            )}

            {allowUsageBased && (
                <p className="text-[13px] leading-relaxed text-muted-foreground">Optional. With no account here, NoClick’s own key runs it and bills the usage.</p>
            )}

            {matchingCredentials.length > 0 && (
                <div>
                    {!compact && <div className={FIELD_LABEL}>Account</div>}
                    <div className="flex items-center gap-1.5">
                        <div className="relative min-w-0 flex-1" ref={dropdownRef}>
                            <button
                                type="button"
                                data-testid="agent-credential-dropdown"
                                aria-haspopup="listbox"
                                aria-expanded={isDropdownOpen}
                                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                                className="group flex h-10 w-full items-center justify-between rounded-xl border border-border bg-transparent px-3.5 text-left text-[14px] transition-colors hover:border-foreground/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-foreground/[0.1]"
                            >
                                <span className={cn('truncate', selectedCredential ? 'text-foreground' : 'text-muted-foreground')}>
                                    {selectedCredential ? selectedCredential.name : allowUsageBased ? 'NoClick’s own key' : 'Choose an account'}
                                </span>
                                <ChevronDown className={cn('ml-2 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:text-foreground', isDropdownOpen && 'rotate-180')} />
                            </button>

                            {isDropdownOpen && (
                                <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-xl border border-border bg-popover shadow-lg animate-fade-in dark:border-foreground/[0.1]">
                                    <div className="relative border-b border-border dark:border-foreground/[0.08]">
                                        <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            ref={searchInputRef}
                                            type="text"
                                            placeholder="Search accounts"
                                            value={searchQuery}
                                            onChange={(e) => setSearchQuery(e.target.value)}
                                            className="w-full bg-transparent py-2.5 pl-9 pr-3 text-[13px] text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                                        />
                                    </div>
                                    <div className="max-h-56 overflow-y-auto scrollbar-subtle">
                                        <button
                                            type="button"
                                            onClick={() => handleSelectCredential(null)}
                                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-muted-foreground transition-colors hover:bg-accent"
                                        >
                                            <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', !selectedCredentialId ? 'bg-muted-foreground' : 'bg-transparent')} />
                                            {allowUsageBased ? 'NoClick’s own key' : 'None'}
                                        </button>
                                        {filteredCredentials.map((cred) => (
                                            <div key={cred.id} className="group flex w-full items-center text-[13px] transition-colors hover:bg-accent">
                                                <button type="button" onClick={() => handleSelectCredential(cred.id)} className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left">
                                                    <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', selectedCredentialId === cred.id ? 'bg-foreground' : 'bg-transparent')} />
                                                    <span className="truncate text-foreground">{cred.name}</span>
                                                </button>
                                                {!compact && (
                                                <button
                                                    type="button"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        openDeleteDialog(cred.id, cred.name);
                                                    }}
                                                    className="mr-1.5 rounded-full p-1.5 text-muted-foreground opacity-0 transition hover:bg-foreground/[0.06] hover:text-red-600 group-hover:opacity-100 focus-visible:opacity-100 dark:hover:text-red-400"
                                                    title="Delete"
                                                    aria-label={`Delete ${cred.name}`}
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </button>
                                                )}
                                            </div>
                                        ))}
                                        {filteredCredentials.length === 0 && searchQuery && <div className="px-3 py-2 text-[13px] text-muted-foreground">No match</div>}
                                    </div>
                                    {methods.length > 0 && (
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setIsDropdownOpen(false);
                                                setConnecting(true);
                                            }}
                                            className="flex w-full items-center gap-2 border-t border-border px-3 py-2.5 text-left text-[13px] text-foreground transition-colors hover:bg-accent dark:border-foreground/[0.08]"
                                        >
                                            <Plus className="h-3.5 w-3.5" />
                                            Connect another account
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>
                        {/* A compact host is a question: it offers picking or connecting, not sharing or deleting. */}
                        {selectedCredential && !compact && (
                            <div className="flex items-center">
                                <button
                                    type="button"
                                    onClick={() => setShareCredential({ id: selectedCredential.id, name: selectedCredential.name })}
                                    className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                    title="Share"
                                    aria-label={`Share ${selectedCredential.name}`}
                                >
                                    <Share2 className="h-3.5 w-3.5" />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => openDeleteDialog(selectedCredential.id, selectedCredential.name)}
                                    className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 dark:hover:text-red-400"
                                    title="Delete"
                                    aria-label={`Delete ${selectedCredential.name}`}
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                </button>
                            </div>
                        )}
                    </div>

                    {/* What connecting proved: a key saved here in full, an older account by what its row remembers. */}
                    {selectedCredential && selectedCredentialId && selectedCredentialId in verifications ? (
                        <ConnectionVerdict className="mt-3" verification={verifications[selectedCredentialId]} providerLabel={providerTitle} />
                    ) : (
                        selectedCredential && <StoredVerdict className="mt-1.5" metadata={selectedCredential.metadata} />
                    )}
                </div>
            )}

            {methods.length > 0 &&
                (connectOpen ? (
                    <div className={cn(matchingCredentials.length > 0 && 'border-t border-border pt-5 dark:border-foreground/[0.08]')}>
                        {matchingCredentials.length > 0 && (
                            <div className="mb-4 flex items-center justify-between gap-3">
                                <p className="text-[14.5px] font-medium text-foreground">Connect another account</p>
                                <button type="button" onClick={() => setConnecting(false)} className={INLINE_ACTION}>
                                    Never mind
                                </button>
                            </div>
                        )}
                        <AiConnect
                            app={providerTitle}
                            methods={methods}
                            credentialIds={credentialIds}
                            onCredentialIdsChange={attachSignIn}
                            onSignedIn={signedIn}
                            onKeySaved={keySaved}
                            // Compact hosts already belong to someone asking.
                            ask={!compact && credentialType ? { credentialType } : undefined}
                        />
                    </div>
                ) : (
                    <button type="button" onClick={() => setConnecting(true)} className={cn(INLINE_ACTION, 'inline-flex items-center gap-1.5')}>
                        <Plus className="h-3.5 w-3.5" />
                        Connect another account
                    </button>
                ))}

            {/* Self-hosted: the CLI runs on this server, as whatever is attached above. */}
            {isLocalEdition() && isCliAgentModel(selectedModel) && (
                <p className="text-[13px] leading-relaxed text-muted-foreground">
                    Runs the <code>{cliHarnessBinary(selectedModel)}</code> CLI on this server with the sign-in or API key attached above. With nothing
                    attached it uses whatever account that CLI is already signed in to on the server.
                </p>
            )}

            {/* Advanced: sandbox environment variables, a SECONDARY credential (agent_env) in the same credentialIds
                map, unrelated to the model's account, so it comes last. */}
            {(!compact || envInUse) && (
                <div>
                    <button
                        type="button"
                        aria-expanded={showAdvanced}
                        onClick={() => setShowAdvanced((v) => !v)}
                        className="flex items-center gap-1 py-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
                    >
                        <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', showAdvanced && 'rotate-90')} />
                        Advanced
                    </button>
                    {showAdvanced && (
                        <div className="space-y-1.5 pb-1">
                            <div className="text-[13px] text-muted-foreground">Environment variables</div>
                            <AgentEnvVarsSection
                                credentialIds={credentialIds}
                                onCredentialIdsChange={onCredentialIdsChange}
                                requestedEnvVars={Array.isArray(agentConfig.agent_env_requested) ? (agentConfig.agent_env_requested as unknown[]) : undefined}
                            />
                            {/* Do NOT claim the model can't see the values: they live in its shell, so any command can
                                print them. Only the prompt is names-only. */}
                            <div className="text-[12px] text-muted-foreground">
                                Available in the agent&apos;s sandbox shell (e.g. $STRIPE_KEY) so it can call APIs directly. Values aren&apos;t written into
                                the prompt, but the agent can read them by running a command, so scope these keys accordingly.
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
        </div>
    );
}
