/**
 * CredentialSelector - reusable UI for selecting or connecting credentials.
 * Uses the shared useCredentialOAuth hook for OAuth logic and credential loading.
 * Supports OAuth credentials, non-OAuth credentials (API keys, tokens), and providers with multiple auth methods.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, ChevronDown, Search, Plus, X, Check, ExternalLink } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useCredentialOAuth } from '~/hooks/useCredentialOAuth';
import { InstanceLimitDialog } from '~/components/utils/InstanceLimitDialog';
import { isInstanceLimitError } from '~/lib/instanceLimitErrors';
import { getProviderConfigNormalized, getProviderConfigByCredentialType, type OAuthProviderConfig } from '~/utils/oauthProviders';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { sendEventAsync } from '~/lib/socket-sender';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import type { CredentialRequest } from './credentialRequest';
import type { CredentialVariable } from '~/hooks/useCredentialVariables';
import { SecretInput } from './SecretInput';
import { FieldRequirementBadge, isFieldFilled } from './FieldRequirementBadge';
import { OAuthErrorPanel } from './OAuthErrorPanel';

// ============================================================================
// Types
// ============================================================================

interface CredentialField {
    name: string;
    label: string;
    type: 'text' | 'password';
    placeholder?: string;
    required: boolean;
}

interface CredentialSchemaInfo {
    title: string;
    description?: string;
    credentialUrl?: string;
    fields: CredentialField[];
    credentialType: string;
}

interface CredentialSelectorProps {
    /** The input request containing credential type info */
    input: CredentialRequest;
    /** Called when a credential is selected (value is the credential ID or {{vars.name}} reference) */
    onCredentialSelect: (credentialId: string) => void;
    /** Currently selected credential ID or variable reference */
    selectedCredentialId?: string;
    /** Node type for accessing schema (optional - used for inline credential forms) */
    nodeType?: string;
    /** Credential variables from set-variable nodes — shown in dropdown as selectable references */
    credentialVariables?: CredentialVariable[];
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Get credential URL where users can obtain their API key/token.
 */
function getCredentialUrl(credentialSchema: any): string | undefined {
    return credentialSchema?.['x-credential-url'];
}

/**
 * Check if credential schema is OAuth-based.
 */
function isOAuthCredentialSchema(credentialSchema: any): boolean {
    return credentialSchema?.['x-credential-type'] === 'oauth';
}

/**
 * Extract field info from JSON Schema for credential forms.
 */
function getFieldsFromSchema(credentialSchema: any): CredentialField[] {
    if (!credentialSchema?.properties) return [];

    const required = credentialSchema.required || [];
    return Object.entries(credentialSchema.properties).map(([name, prop]: [string, any]) => ({
        name,
        label: prop.title || name,
        type: (prop['ui:widget'] === 'password' ? 'password' : 'text') as 'text' | 'password',
        placeholder: prop.placeholder,
        required: required.includes(name)
    }));
}

/**
 * Map schema title to credential_type for saving to DB.
 * Same mapping used in NodeCredentials.tsx
 */
function getCredentialTypeFromSchemaTitle(title: string): string {
    return title
        .replace('Credential', '')
        .replace(/([a-z])([A-Z])/g, '$1_$2')
        .toLowerCase();
}

/**
 * Extract non-OAuth credential schemas from node schema.
 * Returns credential options that can be entered via form (not OAuth).
 */
/**
 * Resolve the OAuth credential schema for a specific credential_type from a
 * node's schema. Used so guided-setup connect can pass the node-specific name
 * and scopes — critical for providers (Microsoft) whose sibling credential
 * types share a provider and, in some cases, identical scopes.
 */
function getOAuthCredentialSchemaForType(
    nodeType: string | undefined,
    credentialType: string | undefined
): any | null {
    if (!nodeType || !credentialType) return null;
    const schema = NODE_SCHEMAS[nodeType];
    const defs = schema?.$defs || schema?.definitions;
    if (!defs) return null;
    for (const def of Object.values(defs) as any[]) {
        if (def?.properties?.credential_type?.const === credentialType) return def;
    }
    return null;
}

function getNonOAuthCredentialSchemas(nodeType: string | undefined): CredentialSchemaInfo[] {
    if (!nodeType) return [];

    const schema = NODE_SCHEMAS[nodeType];
    if (!schema?.properties?.credentials) return [];

    const credentialProp = schema.properties.credentials;

    // Resolve $ref if present
    const resolveRef = (ref: string) => {
        const path = ref.replace('#/$defs/', '');
        return schema.$defs?.[path] || schema.definitions?.[path];
    };

    // Helper to create credential info from schema
    const createCredentialInfo = (credSchema: any): CredentialSchemaInfo | null => {
        // Skip OAuth credentials - those are handled separately
        if (isOAuthCredentialSchema(credSchema)) return null;

        const schemaTitle = credSchema.title || '';
        return {
            title: schemaTitle.replace('Credential', '').trim(),
            description: credSchema.description,
            credentialUrl: getCredentialUrl(credSchema),
            fields: getFieldsFromSchema(credSchema),
            credentialType: getCredentialTypeFromSchemaTitle(schemaTitle),
        };
    };

    const credentials: CredentialSchemaInfo[] = [];

    if (credentialProp.$ref) {
        // Direct $ref - single credential type
        const credentialSchema = resolveRef(credentialProp.$ref);
        if (credentialSchema) {
            const info = createCredentialInfo(credentialSchema);
            if (info) credentials.push(info);
        }
    } else if (credentialProp.anyOf) {
        // anyOf pattern - find all non-null, non-OAuth types with $ref
        const refEntries = credentialProp.anyOf.filter((entry: any) => entry.$ref);
        for (const refEntry of refEntries) {
            const credentialSchema = resolveRef(refEntry.$ref);
            if (credentialSchema) {
                const info = createCredentialInfo(credentialSchema);
                if (info) credentials.push(info);
            }
        }
    }

    return credentials;
}

// ============================================================================
// Component
// ============================================================================

export function CredentialSelector(props: CredentialSelectorProps) {
    return <CredentialSelectorInner {...props} />;
}

function CredentialSelectorInner({
    input,
    onCredentialSelect,
    selectedCredentialId,
    nodeType,
    credentialVariables,
}: CredentialSelectorProps) {
    // Get provider config for this credential type with robust fallback logic
    // IMPORTANT: Backend sends DB credential types (e.g., "google_sheets_oauth")
    // which don't match provider config keys directly. We need to search through
    // all providers' credentialTypes arrays to find the right provider.
    const providerConfig = useMemo(() => {
        // Strategy 1: Try using acceptedCredentialTypes[0] (most reliable)
        if (input.acceptedCredentialTypes && input.acceptedCredentialTypes.length > 0) {
            const config = getProviderConfigByCredentialType(input.acceptedCredentialTypes[0]);
            if (config) {
                console.debug(`[CredentialSelector] Found provider via acceptedCredentialTypes: ${input.acceptedCredentialTypes[0]} → ${config.name}`);
                return config;
            }
        }

        // Strategy 2: Try direct lookup by credentialType (searches all providers' credentialTypes)
        if (input.credentialType) {
            const config = getProviderConfigByCredentialType(input.credentialType);
            if (config) {
                console.debug(`[CredentialSelector] Found provider via credentialType: ${input.credentialType} → ${config.name}`);
                return config;
            }
        }

        // Strategy 3: Try normalized key lookup (fallback for backward compatibility)
        // This handles cases where the key matches a provider alias directly
        if (input.credentialType) {
            // Remove common suffixes that don't match provider keys
            const normalized = input.credentialType
                .replace(/_oauth$/, '')
                .replace(/_pat$/, '')
                .replace(/_api_key$/, '')
                .replace(/_bot_token$/, '')
                .replace(/_bearer_token$/, '')
                .replace(/_access_token$/, '');

            const config = getProviderConfigNormalized(normalized);
            if (config) {
                console.debug(`[CredentialSelector] Found provider via normalized key: ${input.credentialType} → ${normalized} → ${config.name}`);
                return config;
            }
        }

        console.warn(`[CredentialSelector] Could not find provider config for credentialType="${input.credentialType}", acceptedCredentialTypes=${JSON.stringify(input.acceptedCredentialTypes)}`);
        return undefined;
    }, [input.credentialType, input.acceptedCredentialTypes]);

    // Get non-OAuth credential options from node schema (for inline forms)
    const nonOAuthCredentials = useMemo(
        () => getNonOAuthCredentialSchemas(nodeType),
        [nodeType]
    );

    // Use shared OAuth hook
    const {
        availableCredentials,
        loading,
        loadCredentials,
        connect,
        isConnecting,
        connectingProvider,
        error,
        planLimitError: oauthPlanLimitError,
        clearError,
    } = useCredentialOAuth({
        onCredentialCreated: (credentialId) => {
            onCredentialSelect(credentialId);
        },
    });

    // UI state
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const buttonRef = useRef<HTMLButtonElement>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);
    const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, width: 0 });

    // Inline credential form state
    const [isCreatingCredential, setIsCreatingCredential] = useState(false);
    const [selectedCredentialSchema, setSelectedCredentialSchema] = useState<CredentialSchemaInfo | null>(null);
    const [credentialName, setCredentialName] = useState('');
    const [credentialFormData, setCredentialFormData] = useState<Record<string, string>>({});
    const [createLoading, setCreateLoading] = useState(false);
    const [createError, setCreateError] = useState<string | null>(null);
    const [instanceLimitError, setInstanceLimitError] = useState<string | null>(null);

    // Filter credentials to those matching this provider's types
    const matchingCredentials = useMemo(() => {
        // If backend provided specific credential types, use those
        if (input.acceptedCredentialTypes && input.acceptedCredentialTypes.length > 0) {
            return availableCredentials.filter(cred =>
                input.acceptedCredentialTypes!.includes(cred.credential_type)
            );
        }
        // Fall back to provider-based mapping if available
        if (providerConfig) {
            return availableCredentials.filter(cred =>
                providerConfig.credentialTypes.includes(cred.credential_type)
            );
        }
        // Fall back to schema-based mapping (for non-OAuth credentials)
        if (nonOAuthCredentials.length > 0) {
            const schemaCredTypes = nonOAuthCredentials.map(c => c.credentialType);
            return availableCredentials.filter(cred =>
                schemaCredTypes.includes(cred.credential_type)
            );
        }
        return [];
    }, [availableCredentials, providerConfig, input.acceptedCredentialTypes, nonOAuthCredentials]);

    // Credential variables filtered to those matching this credential type
    const matchingVars = useMemo(() => {
        if (!credentialVariables) return [];
        const accepted = input.acceptedCredentialTypes && input.acceptedCredentialTypes.length > 0
            ? input.acceptedCredentialTypes
            : providerConfig?.credentialTypes ?? [];
        return credentialVariables.filter(v =>
            v.credentialTypes.length === 0 || accepted.length === 0 ||
            v.credentialTypes.some(t => accepted.includes(t))
        );
    }, [credentialVariables, input.acceptedCredentialTypes, providerConfig]);

    // Currently selected credential (DB credential or variable reference)
    const selectedCredential = matchingCredentials.find(c => c.id === selectedCredentialId);
    const selectedVarName = useMemo(() => {
        if (!selectedCredentialId?.startsWith('{{vars.')) return undefined;
        return matchingVars.find(v => `{{vars.${v.name}}}` === selectedCredentialId)?.name ?? selectedCredentialId;
    }, [selectedCredentialId, matchingVars]);

    // Filter by search query
    const filteredCredentials = fuzzyFilter(matchingCredentials, searchQuery, cred => [
        { text: cred.name.toLowerCase(), weight: 1, fuzzy: true },
    ]);

    // Update dropdown position when opening
    useEffect(() => {
        if (isDropdownOpen && buttonRef.current) {
            const rect = buttonRef.current.getBoundingClientRect();
            setDropdownPosition({
                top: rect.bottom + 4,
                left: rect.left,
                width: rect.width,
            });
        }
    }, [isDropdownOpen]);

    // Close dropdown when any scrollable ancestor scrolls
    useEffect(() => {
        if (!isDropdownOpen) return;

        const handleScroll = () => {
            setIsDropdownOpen(false);
            setSearchQuery('');
        };

        // Find all scrollable ancestors and attach listeners
        const scrollableAncestors: Element[] = [];
        let element = buttonRef.current?.parentElement;
        while (element) {
            const style = getComputedStyle(element);
            if (
                style.overflow === 'auto' || style.overflow === 'scroll' ||
                style.overflowY === 'auto' || style.overflowY === 'scroll'
            ) {
                scrollableAncestors.push(element);
                element.addEventListener('scroll', handleScroll, { passive: true });
            }
            element = element.parentElement;
        }

        // Also listen to window scroll
        window.addEventListener('scroll', handleScroll, { passive: true });

        return () => {
            scrollableAncestors.forEach(el => el.removeEventListener('scroll', handleScroll));
            window.removeEventListener('scroll', handleScroll);
        };
    }, [isDropdownOpen]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            if (
                dropdownRef.current && !dropdownRef.current.contains(target) &&
                buttonRef.current && !buttonRef.current.contains(target)
            ) {
                setIsDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Focus search when dropdown opens
    useEffect(() => {
        if (isDropdownOpen && searchInputRef.current) {
            searchInputRef.current.focus();
        }
        if (!isDropdownOpen) {
            setSearchQuery('');
        }
    }, [isDropdownOpen]);

    // Handle OAuth connect
    const handleOAuthConnect = useCallback(() => {
        if (!providerConfig || !providerConfig.oauthProvider) return;

        // Resolve the SPECIFIC credential schema for this node so the name and
        // scopes discriminate among a provider's sibling types. Microsoft backs
        // six credential types (Word/Excel/OneDrive/Teams/Outlook/To-Do) from one
        // provider, and Word/Excel/OneDrive request identical scopes — so the
        // backend can only tell them apart by the credential NAME. Passing the
        // provider label ("Microsoft") + empty provider defaults made every
        // Microsoft node collapse onto one type and trip the per-type limit.
        const targetType =
            input.credentialType || input.acceptedCredentialTypes?.[0];
        const oauthSchema = getOAuthCredentialSchemaForType(nodeType, targetType);

        const rawTitle = (oauthSchema?.title || '').replace('Credential', '');
        const defaultName = `${
            rawTitle ? humanizeCredentialLabel(rawTitle) : providerConfig.name
        } - ${new Date().toLocaleDateString()}`;
        // The node's own scopes when known (so the credential is granted what it
        // needs), else the provider defaults.
        const scopes =
            (oauthSchema?.['x-oauth-scopes'] as string[] | undefined) ||
            providerConfig.defaultScopes ||
            [];
        const userScopes = oauthSchema?.['x-oauth-user-scopes'] as
            | string[]
            | undefined;

        // Shopify requires shop parameter
        if (providerConfig.oauthProvider === 'shopify') {
            const shop = prompt('Enter your Shopify store name (e.g., my-store from my-store.myshopify.com):');
            if (!shop) return;
            connect(providerConfig.oauthProvider, defaultName, scopes, shop);
        } else {
            connect(
                providerConfig.oauthProvider,
                defaultName,
                scopes,
                undefined,
                undefined,
                userScopes
            );
        }
    }, [providerConfig, connect, input.credentialType, input.acceptedCredentialTypes, nodeType]);

    // Start creating a new credential inline
    const handleStartCreate = useCallback((schema: CredentialSchemaInfo) => {
        setSelectedCredentialSchema(schema);
        setCredentialName('');
        setCredentialFormData({});
        setCreateError(null);
        setIsCreatingCredential(true);
    }, []);

    // Cancel inline credential creation
    const handleCancelCreate = useCallback(() => {
        setIsCreatingCredential(false);
        setSelectedCredentialSchema(null);
        setCredentialName('');
        setCredentialFormData({});
        setCreateError(null);
    }, []);

    // Update form field
    const handleFormFieldChange = useCallback((fieldName: string, value: string) => {
        setCredentialFormData(prev => ({ ...prev, [fieldName]: value }));
    }, []);

    // Create the credential
    const handleCreateCredential = useCallback(async () => {
        if (!selectedCredentialSchema) return;

        setCreateError(null);
        setCreateLoading(true);

        try {
            const response = await sendEventAsync({
                event_name: 'credential:create',
                request_id: `create-${Date.now()}`,
                name: credentialName || `${selectedCredentialSchema.title} - ${new Date().toLocaleDateString()}`,
                credential_type: selectedCredentialSchema.credentialType,
                credential_data: credentialFormData,
                metadata: {}
            });

            if (response?.success && response.credential) {
                // Invalidate cache and reload credentials list
                invalidateCredentialsCache();
                await loadCredentials();

                // Auto-select the newly created credential
                onCredentialSelect(response.credential.id);

                // Reset form
                handleCancelCreate();
            } else {
                const errMsg = response?.error || response?.message || 'Failed to create credential';
                if (isInstanceLimitError(errMsg)) {
                    setInstanceLimitError(errMsg);
                } else {
                    setCreateError(errMsg);
                }
            }
        } catch (err) {
            console.error('[CredentialSelector] Error creating credential:', err);
            const errMsg = err instanceof Error ? err.message : 'Failed to create credential';
            if (isInstanceLimitError(errMsg)) {
                setInstanceLimitError(errMsg);
            } else {
                setCreateError(errMsg);
            }
        } finally {
            setCreateLoading(false);
        }
    }, [selectedCredentialSchema, credentialName, credentialFormData, loadCredentials, onCredentialSelect, handleCancelCreate]);

    // If we don't recognize the provider AND have no non-OAuth credential options,
    // show a helpful message. Otherwise, we can still render the non-OAuth forms.
    if (!providerConfig && nonOAuthCredentials.length === 0) {
        console.warn(`[CredentialSelector] Unknown provider: "${input.credentialType}" and no schema found`);
        return (
            <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                <div className="text-xs text-amber-600 dark:text-amber-400 mb-1">Unknown credential type: {input.credentialType}</div>
                <div className="text-[10px] text-muted-foreground dark:text-white/50">
                    Configure this credential manually in the node settings after generation.
                </div>
            </div>
        );
    }

    const ProviderIcon = providerConfig?.Icon;
    const hasOAuth = !!providerConfig?.oauthProvider;
    const isThisProviderConnecting = connectingProvider === providerConfig?.oauthProvider;
    const hasConnectedCredential = !!selectedCredential;
    // Check if there are non-OAuth credential options available (API keys, tokens, etc.)
    const hasNonOAuthOption = nonOAuthCredentials.length > 0;
    // Derive display name from providerConfig or input
    const providerDisplayName = providerConfig?.name || input.credentialType?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Unknown';

    // Render dropdown in a portal to escape overflow clipping
    const renderDropdown = () => {
        if (!isDropdownOpen) return null;

        const dropdown = (
            <div
                ref={dropdownRef}
                style={{
                    position: 'fixed',
                    top: dropdownPosition.top,
                    left: dropdownPosition.left,
                    width: dropdownPosition.width,
                    zIndex: 9999,
                }}
                className="bg-card border border-border rounded-lg shadow-2xl overflow-hidden"
            >
                {/* Search */}
                <div className="relative border-b border-border">
                    <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                    <input
                        ref={searchInputRef}
                        type="text"
                        placeholder="Search..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-8 pr-2.5 py-2 bg-transparent text-foreground/80 placeholder:text-[hsl(var(--placeholder))] text-xs focus:outline-none"
                    />
                </div>

                <div className="max-h-40 overflow-y-auto scrollbar-subtle">
                    {/* None option */}
                    <button
                        type="button"
                        onClick={() => {
                            onCredentialSelect('');
                            setIsDropdownOpen(false);
                        }}
                        className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center justify-between"
                    >
                        <span className="text-muted-foreground/70 dark:text-zinc-600 italic">None</span>
                        {!selectedCredentialId && <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground dark:bg-zinc-500" />}
                    </button>

                    {/* Variable references from set-variable nodes */}
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
                                        onCredentialSelect(varRef);
                                        setIsDropdownOpen(false);
                                    }}
                                    className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center justify-between group border-t border-border/30 dark:border-zinc-800/30"
                                >
                                    <span className="text-emerald-600 dark:text-emerald-300">{v.name}</span>
                                    {selectedCredentialId === varRef && (
                                        <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400" />
                                    )}
                                </button>
                            );
                        })}
                    </>)}

                    {/* Credential options */}
                    {filteredCredentials.map((cred) => (
                        <button
                            key={cred.id}
                            type="button"
                            onClick={() => {
                                onCredentialSelect(cred.id);
                                setIsDropdownOpen(false);
                            }}
                            className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center justify-between border-t border-border/30 dark:border-zinc-800/30"
                        >
                            <div className="flex-1 min-w-0 pr-2">
                                <div className="text-foreground/80 truncate">{cred.name}</div>
                                {cred.metadata?.email && (
                                    <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 truncate">{cred.metadata.email}</div>
                                )}
                            </div>
                            {selectedCredentialId === cred.id && (
                                <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 shrink-0" />
                            )}
                        </button>
                    ))}

                    {filteredCredentials.length === 0 && searchQuery && (
                        <div className="border-t border-border/30 dark:border-zinc-800/30">
                            <div className="px-3 py-2 text-xs text-muted-foreground/70 dark:text-zinc-600 italic">
                                No matches
                            </div>
                            {nonOAuthCredentials.length > 0 && (
                                <div className="pb-1">
                                    {nonOAuthCredentials.map((schema) => (
                                        <button
                                            key={schema.credentialType}
                                            type="button"
                                            onClick={() => {
                                                handleStartCreate(schema);
                                                setIsDropdownOpen(false);
                                                setSearchQuery('');
                                            }}
                                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                                        >
                                            <Plus className="h-3.5 w-3.5" />
                                            Create new {schema.title}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Empty state when no credentials or variables at all */}
                    {matchingCredentials.length === 0 && matchingVars.length === 0 && !loading && (
                        <div className="px-3 py-3 text-xs text-muted-foreground dark:text-zinc-500 text-center">
                            <div className="mb-1">No {providerDisplayName} credentials found.</div>
                            <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">{hasOAuth ? 'Connect an account below.' : 'Create a credential below.'}</div>
                        </div>
                    )}
                </div>
            </div>
        );

        // Render in portal to escape overflow
        return createPortal(dropdown, document.body);
    };

    return (
        <div className="space-y-2">
            {/* OAuth / credential-creation error. Uses the shared panel so the
                Reconnect button hooks back into the same handleOAuthConnect flow
                — important for Google's missing-scopes rejection where the user
                needs to redo consent with all boxes ticked. */}
            {error && (
                <OAuthErrorPanel
                    message={error}
                    onReconnect={handleOAuthConnect}
                    onDismiss={clearError}
                    isReconnecting={isThisProviderConnecting}
                />
            )}

            {/* Credential dropdown */}
            <div className="relative">
                <button
                    ref={buttonRef}
                    type="button"
                    onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                    className={cn(
                        "w-full px-3 py-2 text-sm rounded-lg border text-left flex items-center justify-between transition-all",
                        selectedCredential
                            ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
                            : "bg-foreground/[0.03] border-border dark:border-white/[0.08] text-muted-foreground dark:text-white/70 hover:bg-foreground/[0.05] hover:border-muted-foreground/40 dark:hover:border-white/[0.12]"
                    )}
                >
                    <span className="truncate flex items-center gap-2">
                        {loading ? (
                            <span className="text-muted-foreground dark:text-white/50">Loading credentials...</span>
                        ) : selectedCredential ? (
                            <>
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                                {selectedCredential.name}
                            </>
                        ) : selectedVarName ? (
                            <>
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                                <span className="text-emerald-600 dark:text-emerald-300">{selectedVarName}</span>
                            </>
                        ) : (matchingCredentials.length > 0 || matchingVars.length > 0) ? (
                            'Select credential...'
                        ) : (
                            <span className="text-muted-foreground dark:text-white/50">No credentials found</span>
                        )}
                    </span>
                    <ChevronDown className={cn(
                        "w-3.5 h-3.5 transition-transform shrink-0 ml-2",
                        isDropdownOpen && "rotate-180"
                    )} />
                </button>

                {renderDropdown()}
            </div>

            {/* OAuth Connect button */}
            {hasOAuth && ProviderIcon && (
                <button
                    onClick={handleOAuthConnect}
                    disabled={isConnecting}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm text-foreground/90 bg-foreground/[0.08] hover:bg-foreground/[0.14] disabled:bg-muted dark:disabled:bg-white/[0.04] disabled:text-muted-foreground/60 dark:disabled:text-white/40 disabled:cursor-not-allowed border border-border dark:border-white/[0.12] hover:border-muted-foreground/40 dark:hover:border-white/[0.22] disabled:border-border/50 dark:disabled:border-white/[0.06] rounded-lg transition-all"
                >
                    {isThisProviderConnecting ? (
                        <>
                            <div className="animate-spin w-4 h-4 border-2 border-foreground/30 border-t-foreground rounded-full" />
                            Connecting...
                        </>
                    ) : (
                        <>
                            {ProviderIcon && <BrandIcon Icon={ProviderIcon} iconColor={providerConfig?.iconColor} className="w-4 h-4" />}
                            {hasConnectedCredential
                                ? `Connect Another ${providerDisplayName} Account`
                                : `Connect ${providerDisplayName}`
                            }
                        </>
                    )}
                </button>
            )}

            {/* Non-OAuth credential options (API keys, tokens, etc.) */}
            {hasNonOAuthOption && !isCreatingCredential && (
                <div className="space-y-1.5">
                    {/* Divider when both OAuth and non-OAuth are available */}
                    {hasOAuth && (
                        <div className="flex items-center gap-2 py-1">
                            <div className="flex-1 h-px bg-foreground/[0.08]" />
                            <span className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">or</span>
                            <div className="flex-1 h-px bg-foreground/[0.08]" />
                        </div>
                    )}

                    {/* Show create buttons for each non-OAuth credential type */}
                    {nonOAuthCredentials.map((schema) => (
                        <div key={schema.credentialType}>
                            <button
                                onClick={() => handleStartCreate(schema)}
                                className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-muted/50 dark:bg-zinc-900/50 hover:bg-muted dark:hover:bg-zinc-900 border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-lg transition-all"
                            >
                                <Plus className="h-3.5 w-3.5" />
                                {hasOAuth ? `Use ${schema.title} instead` : `Add ${schema.title}`}
                            </button>
                            {/* Credential URL link - helps users find where to get their API key */}
                            {schema.credentialUrl && (
                                <a
                                    href={schema.credentialUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center justify-center gap-1 mt-2.5 text-[11px] text-blue-600/80 hover:text-blue-700 dark:text-blue-400/80 dark:hover:text-blue-300 transition-colors"
                                >
                                    Get your {schema.title.toLowerCase().includes('api') ? 'API key' : 'credentials'} here
                                    <ExternalLink className="w-2.5 h-2.5" />
                                </a>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {/* Inline credential creation form */}
            {isCreatingCredential && selectedCredentialSchema && (
                <div className="p-3 rounded-lg bg-muted/50 dark:bg-zinc-900/50 border border-border space-y-3">
                    <div className="flex items-center justify-between">
                        <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                            New {selectedCredentialSchema.title}
                        </div>
                        <button
                            onClick={handleCancelCreate}
                            className="p-1 hover:bg-accent rounded transition-colors"
                        >
                            <X className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
                        </button>
                    </div>

                    {/* Description */}
                    {selectedCredentialSchema.description && (
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 leading-relaxed">
                            {selectedCredentialSchema.description}
                        </div>
                    )}

                    {/* Credential URL link */}
                    {selectedCredentialSchema.credentialUrl && (
                        <a
                            href={selectedCredentialSchema.credentialUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
                        >
                            Get your credentials here
                            <ExternalLink className="w-3 h-3" />
                        </a>
                    )}

                    {/* Credential Name (optional) */}
                    <div className="space-y-1">
                        <label className="flex items-center gap-2 text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                            Name
                            <FieldRequirementBadge isRequired={false} />
                        </label>
                        <input
                            type="text"
                            value={credentialName}
                            onChange={(e) => setCredentialName(e.target.value)}
                            placeholder={`My ${selectedCredentialSchema.title}`}
                            className="w-full px-2.5 py-1.5 text-xs bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/40 dark:focus:border-zinc-700 transition-colors"
                        />
                    </div>

                    {/* Credential Fields */}
                    {selectedCredentialSchema.fields.map((field) => (
                        <div key={field.name} className="space-y-1">
                            <label className="flex items-center gap-2 text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                                {field.label}
                                <FieldRequirementBadge isRequired={field.required} isFilled={isFieldFilled(credentialFormData[field.name])} />
                            </label>
                            {field.type === 'password' ? (
                                <SecretInput
                                    value={credentialFormData[field.name] || ''}
                                    onChange={(e) => handleFormFieldChange(field.name, e.target.value)}
                                    placeholder={field.placeholder}
                                    required={field.required}
                                    inputClassName="w-full px-2.5 py-1.5 text-xs bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/40 dark:focus:border-zinc-700 transition-colors font-mono"
                                />
                            ) : (
                                <input
                                    type={field.type}
                                    value={credentialFormData[field.name] || ''}
                                    onChange={(e) => handleFormFieldChange(field.name, e.target.value)}
                                    placeholder={field.placeholder}
                                    required={field.required}
                                    className="w-full px-2.5 py-1.5 text-xs bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/40 dark:focus:border-zinc-700 transition-colors font-mono"
                                />
                            )}
                        </div>
                    ))}

                    {/* Error Message */}
                    {createError && (
                        <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20">
                            <div className="text-xs text-red-600 dark:text-red-400">{createError}</div>
                        </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2 pt-1">
                        <button
                            onClick={handleCancelCreate}
                            className="flex-1 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleCreateCredential}
                            disabled={createLoading || selectedCredentialSchema.fields.filter(f => f.required).some(f => !credentialFormData[f.name])}
                            className="flex-1 px-2.5 py-1.5 text-xs text-foreground bg-foreground/20 hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground/70 dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-border dark:border-zinc-700 hover:border-border dark:hover:border-zinc-600 disabled:border-border rounded-lg transition-all flex items-center justify-center gap-1"
                        >
                            {createLoading ? (
                                'Creating...'
                            ) : (
                                <>
                                    <Check className="h-3 w-3" />
                                    Create
                                </>
                            )}
                        </button>
                    </div>
                </div>
            )}

            {/* Connected account info */}
            {selectedCredential?.metadata?.email && (
                <div className="flex items-center gap-1.5 px-1">
                    <CheckCircle2 className="w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                    <span className="text-[11px] text-muted-foreground dark:text-zinc-500">{selectedCredential.metadata.email}</span>
                </div>
            )}

            <InstanceLimitDialog
                isOpen={!!instanceLimitError || !!oauthPlanLimitError}
                onOpenChange={(open) => { if (!open) { setInstanceLimitError(null); clearError(); } }}
                errorMessage={instanceLimitError || oauthPlanLimitError || ''}
            />
        </div>
    );
}
