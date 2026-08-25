// MCPCredentialForm component handles dynamic OAuth discovery for MCP Server nodes.
// When the user enters an MCP server URL, it automatically discovers if OAuth is required
// and shows a "Connect" button to initiate the OAuth flow.

import { useState, useEffect, useCallback, useRef } from 'react';
import { Key, Link2, ExternalLink, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { useMCPOAuth } from '~/hooks/oauth/useMCPOAuth';
import { sendEventAsync } from '~/lib/socket-sender';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';

interface Credential {
    id: string;
    name: string;
    credential_type: string;
    metadata?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

interface MCPCredentialFormProps {
    /** Server URL from config (triggers OAuth discovery) */
    serverUrl: string | undefined;
    /** Current credential IDs */
    credentialIds: Record<string, string>;
    /** Callback when credential selection changes */
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
}

export function MCPCredentialForm({
    serverUrl,
    credentialIds,
    onCredentialIdsChange,
}: MCPCredentialFormProps) {
    const [authType, setAuthType] = useState<'none' | 'api_key' | 'oauth'>('none');
    const [apiKey, setApiKey] = useState('');
    const [customHeaders, setCustomHeaders] = useState<Record<string, string>>({});
    const [availableCredentials, setAvailableCredentials] = useState<Credential[]>([]);
    const [credentialsLoading, setCredentialsLoading] = useState(true);
    const [createLoading, setCreateLoading] = useState(false);
    const [createError, setCreateError] = useState<string | null>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);

    // Track the last discovered URL to avoid redundant discoveries
    const lastDiscoveredUrlRef = useRef<string | null>(null);

    // MCP OAuth hook
    const {
        discover,
        connect,
        isDiscovering,
        isConnecting,
        discoveryResult,
        error: oauthError,
        clearDiscovery,
    } = useMCPOAuth({
        onCredentialCreated: (credentialId, credentialName) => {
            console.log('[MCPCredentialForm] Credential created:', credentialId, credentialName);
            // Update credential selection
            onCredentialIdsChange({
                ...credentialIds,
                mcp_oauth: credentialId,
            });
            // Refresh credentials list
            loadCredentials();
        },
        onError: (error) => {
            console.error('[MCPCredentialForm] OAuth error:', error);
            if (isPlanLimitError(error)) {
                setPlanLimitError(error);
            } else {
                setCreateError(error);
            }
        },
    });

    // Load available MCP OAuth credentials
    const loadCredentials = useCallback(async () => {
        try {
            setCredentialsLoading(true);
            const response = await sendEventAsync({
                event_name: 'credential:list',
                request_id: `cred-list-${Date.now()}`,
            });

            if (response?.credentials) {
                // Filter for MCP OAuth credentials
                const mcpCredentials = response.credentials.filter(
                    (cred: Credential) => cred.credential_type === 'mcp_oauth'
                );
                setAvailableCredentials(mcpCredentials);
            }
        } catch (err) {
            console.error('[MCPCredentialForm] Error loading credentials:', err);
        } finally {
            setCredentialsLoading(false);
        }
    }, []);

    // Load credentials on mount
    useEffect(() => {
        loadCredentials();
    }, [loadCredentials]);

    // Trigger OAuth discovery when server URL changes
    useEffect(() => {
        if (!serverUrl || serverUrl === lastDiscoveredUrlRef.current) {
            return;
        }

        // Validate URL format before discovering
        try {
            new URL(serverUrl);
        } catch {
            // Invalid URL - clear discovery
            clearDiscovery();
            lastDiscoveredUrlRef.current = null;
            return;
        }

        // Discover OAuth requirements
        lastDiscoveredUrlRef.current = serverUrl;
        discover(serverUrl);
    }, [serverUrl, discover, clearDiscovery]);

    // Auto-select auth type based on discovery
    useEffect(() => {
        if (discoveryResult?.requires_oauth) {
            setAuthType('oauth');
        }
    }, [discoveryResult]);

    // Handle API key credential creation
    const handleCreateApiKeyCredential = useCallback(async () => {
        if (!serverUrl || !apiKey) return;

        setCreateLoading(true);
        setCreateError(null);

        try {
            const domain = new URL(serverUrl).hostname;
            const response = await sendEventAsync({
                event_name: 'credential:create',
                request_id: `create-mcp-apikey-${Date.now()}`,
                name: `MCP API Key (${domain})`,
                credential_type: 'mcp_api_key',
                credential_data: {
                    api_key: apiKey,
                    custom_headers: Object.keys(customHeaders).length > 0 ? customHeaders : undefined,
                },
                metadata: {
                    server_url: serverUrl,
                },
            });

            if (response?.success && response.credential) {
                invalidateCredentialsCache();
                await loadCredentials();
                onCredentialIdsChange({
                    ...credentialIds,
                    mcp_api_key: response.credential.id,
                });
                setApiKey('');
                setCustomHeaders({});
            } else {
                const errMsg = response?.error || response?.message || 'Failed to create credential';
                if (isPlanLimitError(errMsg)) {
                    setPlanLimitError(errMsg);
                } else {
                    setCreateError(errMsg);
                }
            }
        } catch (err) {
            console.error('[MCPCredentialForm] Error creating credential:', err);
            const errMsg = err instanceof Error ? err.message : 'Failed to create credential';
            if (isPlanLimitError(errMsg)) {
                setPlanLimitError(errMsg);
            } else {
                setCreateError(errMsg);
            }
        } finally {
            setCreateLoading(false);
        }
    }, [serverUrl, apiKey, customHeaders, loadCredentials, credentialIds, onCredentialIdsChange]);

    // Get matching credentials for the current server URL
    // Get MCP OAuth credentials matching the current server URL
    const matchingCredentials = availableCredentials.filter(
        cred => cred.credential_type === 'mcp_oauth' && cred.metadata?.server_url === serverUrl
    );

    const selectedCredentialId = credentialIds.mcp_oauth || credentialIds.mcp_api_key;
    const selectedCredential = availableCredentials.find(c => c.id === selectedCredentialId);

    // Don't show if no server URL
    if (!serverUrl) {
        return (
            <div className="p-4 rounded-lg bg-card/30 border border-border/50 dark:border-zinc-800/50">
                <div className="flex items-center gap-2 text-muted-foreground dark:text-zinc-500 text-sm">
                    <Link2 className="w-4 h-4" />
                    <span>Enter a server URL above to configure authentication</span>
                </div>
            </div>
        );
    }

    // Show loading while fetching credentials
    if (credentialsLoading) {
        return (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Loading credentials...</span>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                Authentication
            </div>

            {/* Discovery Status */}
            {isDiscovering && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Discovering authentication requirements...</span>
                </div>
            )}

            {/* OAuth Required Banner */}
            {discoveryResult?.requires_oauth && !isDiscovering && (
                <div className="p-3 rounded-lg bg-muted/50 border border-border/50 dark:border-zinc-700/50">
                    <div className="flex items-start gap-2">
                        <Key className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                        <div className="flex-1">
                            <div className="text-sm text-foreground/80 font-medium">
                                {discoveryResult.provider_name || 'OAuth'} Authentication Required
                            </div>
                            <div className="text-xs text-muted-foreground dark:text-zinc-500 mt-1">
                                This MCP server requires OAuth authentication to access its tools.
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Error Banner */}
            {(oauthError || createError) && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
                        <div className="text-sm text-red-600 dark:text-red-400">{oauthError || createError}</div>
                    </div>
                </div>
            )}

            {/* Auth Type Selector (only show if not OAuth required) */}
            {!discoveryResult?.requires_oauth && !isDiscovering && (
                <div className="flex gap-2">
                    <button
                        type="button"
                        onClick={() => setAuthType('none')}
                        className={`flex-1 px-3 py-2 text-xs rounded-lg border transition-all ${
                            authType === 'none'
                                ? 'bg-secondary border-foreground/30 text-foreground'
                                : 'bg-card/50 border-border text-muted-foreground dark:text-zinc-500 hover:border-foreground/20'
                        }`}
                    >
                        No Auth
                    </button>
                    <button
                        type="button"
                        onClick={() => setAuthType('api_key')}
                        className={`flex-1 px-3 py-2 text-xs rounded-lg border transition-all ${
                            authType === 'api_key'
                                ? 'bg-secondary border-foreground/30 text-foreground'
                                : 'bg-card/50 border-border text-muted-foreground dark:text-zinc-500 hover:border-foreground/20'
                        }`}
                    >
                        API Key
                    </button>
                </div>
            )}

            {/* Connected Credential Display */}
            {selectedCredential && (
                <div className="p-3 rounded-lg bg-card/50 border border-border">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <CheckCircle2 className="w-4 h-4 text-green-500" />
                            <div>
                                <div className="text-sm text-foreground">{selectedCredential.name}</div>
                                <div className="text-xs text-muted-foreground dark:text-zinc-500">
                                    {selectedCredential.credential_type === 'mcp_oauth' ? 'OAuth' : 'API Key'}
                                </div>
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => {
                                const newIds = { ...credentialIds };
                                delete newIds.mcp_oauth;
                                delete newIds.mcp_api_key;
                                onCredentialIdsChange(newIds);
                            }}
                            className="text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors"
                        >
                            Disconnect
                        </button>
                    </div>
                </div>
            )}

            {/* OAuth Connect Button */}
            {discoveryResult?.requires_oauth && !selectedCredential && (
                <div className="space-y-3">
                    {/* Select existing credential if available */}
                    {matchingCredentials.length > 0 && (
                        <div className="space-y-2">
                            <div className="text-xs text-muted-foreground dark:text-zinc-500">Existing credentials:</div>
                            {matchingCredentials.map(cred => (
                                <button
                                    key={cred.id}
                                    type="button"
                                    onClick={() => onCredentialIdsChange({
                                        ...credentialIds,
                                        mcp_oauth: cred.id,
                                    })}
                                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left bg-card/50 border border-border rounded-lg hover:bg-accent hover:border-foreground/20 transition-all"
                                >
                                    <Key className="w-4 h-4 text-muted-foreground dark:text-zinc-500" />
                                    <span className="text-foreground/80">{cred.name}</span>
                                </button>
                            ))}
                            <div className="text-center text-xs text-muted-foreground/70 dark:text-zinc-600">or</div>
                        </div>
                    )}

                    {/* Connect new OAuth */}
                    <button
                        type="button"
                        onClick={() => connect(serverUrl)}
                        disabled={isConnecting}
                        className="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium text-foreground bg-foreground/20 hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground dark:disabled:text-zinc-500 disabled:cursor-not-allowed rounded-lg transition-all"
                    >
                        {isConnecting ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Connecting...
                            </>
                        ) : (
                            <>
                                <ExternalLink className="w-4 h-4" />
                                Connect {discoveryResult.provider_name || 'OAuth'}
                            </>
                        )}
                    </button>
                </div>
            )}

            {/* API Key Form */}
            {authType === 'api_key' && !discoveryResult?.requires_oauth && !selectedCredential && (
                <div className="space-y-3 p-4 rounded-lg bg-card/50 border border-border">
                    <div className="space-y-1.5">
                        <label htmlFor="mcp-api-key-input" className="block text-xs text-muted-foreground dark:text-zinc-500">API Key</label>
                        <input
                            id="mcp-api-key-input"
                            type="password"
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                            placeholder="Enter your API key"
                            className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors font-mono"
                        />
                    </div>

                    <button
                        type="button"
                        onClick={handleCreateApiKeyCredential}
                        disabled={!apiKey || createLoading}
                        className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm text-foreground bg-foreground/20 hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground dark:disabled:text-zinc-600 disabled:cursor-not-allowed rounded-lg transition-all"
                    >
                        {createLoading ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Saving...
                            </>
                        ) : (
                            <>
                                <Key className="w-4 h-4" />
                                Save Credential
                            </>
                        )}
                    </button>
                </div>
            )}

            {/* No auth message */}
            {authType === 'none' && !discoveryResult?.requires_oauth && !isDiscovering && (
                <div className="text-xs text-muted-foreground dark:text-zinc-500 italic">
                    No authentication will be used for this MCP server.
                </div>
            )}

            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => { if (!open) setPlanLimitError(null); }}
                errorMessage={planLimitError || ''}
            />
        </div>
    );
}
