// The ONE OAuth connect UI: pre-connect inputs (Shopify store, Zendesk subdomain,
// Atlassian site, BYOO client id/secret), their normalization, the multi-account
// selection step, the error/reconnect panel, and the Connect button. It is presentational
// — the connect ENGINE (useOAuthConnect / useCredentialOAuth) is injected — so the in-app
// credential UI and the public provide link render this exact component and therefore expose
// the exact same credential mechanisms. Provider-intrinsic inputs come from the provider
// config (getOAuthConnectInput); schema-flag inputs (custom client, user scopes) are passed
// in (from the node schema in-app, from the backend method on the provide link). Added so a
// provider that needs an extra input can't work in one surface and silently break the other.

import { useEffect, useState, type ComponentType } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { SecretInput } from '~/components/workflow/SecretInput';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { OAuthErrorPanel } from '~/components/workflow/OAuthErrorPanel';
import { getOAuthConnectInput, providerSupportsOrgConsent } from '~/utils/oauthProviders';
import { getSchemaTitleFromCredentialType } from '~/utils/credentialTypes';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import type { OAuthSelectionOption } from '~/hooks/useOAuthConnect';
import { useInstanceOAuthApp } from '~/hooks/useInstanceOAuthApp';
import { InstanceOAuthAppForm } from '~/components/credential/InstanceOAuthAppForm';
import { InstanceSetupCard } from '~/components/credential/InstanceSetupCard';

/** The injected connect engine's connect() — positional, provider-routed (see useOAuthConnect). */
export type OAuthConnectFn = (
    provider: string,
    name: string,
    scopes?: string[],
    shopName?: string,
    atlassianSite?: string,
    userScopes?: string[],
    customClientCredentials?: { client_id: string; client_secret: string }
) => void;

/** Tenant-wide admin consent (providers with `supportsOrgConsent`) — see useOAuthConnect. */
export type OAuthOrgConsentFn = (provider: string, name: string, scopes?: string[]) => void;

export interface OAuthConnectFormProps {
    provider: string;
    credentialType: string;
    /** Provider display name (button/help copy). */
    displayName: string;
    Icon: ComponentType<{ className?: string }>;
    iconColor?: string;
    scopes: string[];
    userScopes?: string[];
    /** `x-oauth-supports-custom-client`: offer an optional BYOO OAuth app. */
    supportsCustomClient?: boolean;
    /** `x-oauth-requires-custom-client`: BYOO client id/secret are mandatory. */
    requiresCustomClient?: boolean;
    /** `x-oauth-redirect-uri`: redirect URI to display when requiring a custom client. */
    redirectUri?: string;
    /** Existing credential of this type? → "Connect Another Account". */
    hasExistingCredential?: boolean;
    // --- injected engine (shared between surfaces) ---
    connect: OAuthConnectFn;
    /** Offered only when the provider supports org-wide consent; omitted = no offer. */
    connectOrgConsent?: OAuthOrgConsentFn;
    connectingProvider: string | null;
    isConnecting: boolean;
    error?: string | null;
    /** Optional help URL forwarded to OAuthErrorPanel (e.g. apply for API access). */
    errorHelpUrl?: string;
    onClearError?: () => void;
    pendingSelection?: {
        provider: string;
        options: OAuthSelectionOption[];
    } | null;
    onResolvePendingSelection?: (optionId: string) => void;
    onCancel?: () => void;
    /** Gate (plan limit / permission). Return false to block; default allow. */
    canConnect?: () => boolean;
    /**
     * Offer to register this instance's OAuth app when none exists (self-hosted).
     * Opt-in because it writes instance config over an authenticated socket: the
     * builder passes it, the public credential-provide page must not.
     */
    canConfigureInstanceApp?: boolean;
}

const INPUT_CLASS =
    'w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-ring/30 transition-colors font-mono';

function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Strip protocol/path and the domain suffix, lowercased — the tenant slug the OAuth host needs. */
function normalizeConnectInput(raw: string, suffix: string): string {
    return raw
        .trim()
        .toLowerCase()
        .replace(/^https?:\/\//, '')
        .replace(/\/.*$/, '')
        .replace(new RegExp(escapeRegExp(suffix) + '$'), '');
}

/**
 * Schema metadata stores callback paths rather than a hosted deployment URL.
 * Resolve those paths only in the browser so self-hosted operators see their
 * own installation origin. Absolute values remain supported for providers
 * whose callback is intentionally external.
 */
export function resolveOAuthRedirectUri(
    redirectUri: string | undefined,
    installationOrigin: string
): string | undefined {
    if (!redirectUri || !redirectUri.startsWith('/')) return redirectUri;
    if (!installationOrigin) return redirectUri;
    return `${installationOrigin.replace(/\/$/, '')}${redirectUri}`;
}

export function OAuthConnectForm({
    provider,
    credentialType,
    displayName,
    Icon,
    iconColor,
    scopes,
    userScopes,
    supportsCustomClient,
    requiresCustomClient,
    redirectUri,
    hasExistingCredential,
    connect,
    connectOrgConsent,
    connectingProvider,
    isConnecting,
    error,
    errorHelpUrl,
    onClearError,
    pendingSelection,
    onResolvePendingSelection,
    onCancel,
    canConnect,
    canConfigureInstanceApp = false,
}: OAuthConnectFormProps) {
    const connectInput = getOAuthConnectInput(provider, credentialType);
    // No-op on hosted: the hook reports configured without a request.
    const instanceApp = useInstanceOAuthApp(canConfigureInstanceApp ? provider : undefined);
    const [inputValue, setInputValue] = useState('');
    const [showCustomFields, setShowCustomFields] = useState(false);
    const [clientId, setClientId] = useState('');
    const [clientSecret, setClientSecret] = useState('');
    const [installationOrigin, setInstallationOrigin] = useState('');

    useEffect(() => {
        setInstallationOrigin(window.location.origin);
    }, []);

    const displayedRedirectUri = resolveOAuthRedirectUri(
        redirectUri,
        installationOrigin
    );

    const isThisProviderConnecting = connectingProvider === provider;
    const showPendingSelection =
        pendingSelection?.provider === provider &&
        Array.isArray(pendingSelection.options) &&
        pendingSelection.options.length > 0;

    const normalizedTenant = connectInput
        ? normalizeConnectInput(inputValue, connectInput.suffix)
        : '';
    const inputMissing = connectInput ? !normalizedTenant : false;
    const byooMissing =
        !!requiresCustomClient && (!clientId.trim() || !clientSecret.trim());

    // Name the credential after its SPECIFIC type, not the provider label.
    // One provider can back many credential types (Microsoft → Word/Excel/
    // OneDrive/…), and the backend derives the DB credential_type from this
    // name. Naming everything "Microsoft - date" made every Microsoft node
    // collapse onto one type and trip the per-type credential limit.
    const newCredentialName = () => {
        const schemaTitle = getSchemaTitleFromCredentialType(credentialType);
        const credentialLabel = schemaTitle
            ? humanizeCredentialLabel(schemaTitle.replace('Credential', ''))
            : displayName;
        return `${credentialLabel} - ${new Date().toLocaleDateString()}`;
    };

    // Shared trigger so the Connect button and the error panel's Reconnect fire the exact
    // same flow. No-op when a gate (plan limit) or a required input isn't satisfied.
    const triggerConnect = () => {
        if (canConnect && !canConnect()) return;
        const name = newCredentialName();
        let shopArg: string | undefined;
        let siteArg: string | undefined;
        if (connectInput) {
            if (!normalizedTenant) return;
            if (connectInput.kind === 'site') siteArg = normalizedTenant;
            else shopArg = normalizedTenant; // shop | subdomain both ride the 4th arg
        }
        let customClient:
            | { client_id: string; client_secret: string }
            | undefined;
        if (
            requiresCustomClient ||
            (supportsCustomClient && showCustomFields)
        ) {
            const id = clientId.trim();
            const secret = clientSecret.trim();
            if (requiresCustomClient && (!id || !secret)) return;
            if (id && secret)
                customClient = { client_id: id, client_secret: secret };
        }
        connect(
            provider,
            name,
            scopes,
            shopArg,
            siteArg,
            userScopes && userScopes.length ? userScopes : undefined,
            customClient
        );
    };

    // Org-wide consent chains into a normal sign-in that mints a credential, so it
    // rides the same gate as Connect.
    const offersOrgConsent = !!connectOrgConsent && providerSupportsOrgConsent(provider);
    const triggerOrgConsent = () => {
        if (!connectOrgConsent) return;
        if (canConnect && !canConnect()) return;
        connectOrgConsent(provider, newCredentialName(), scopes);
    };

    // Self-hosted with no OAuth app for this provider: Connect would open a
    // popup onto an explainer page. Ask for the app here instead — this panel is
    // where nearly everyone meets the problem, and it is two fields.
    if (canConfigureInstanceApp && !instanceApp.loading && !instanceApp.configured) {
        return (
            <div className="max-w-md">
                <InstanceSetupCard
                    title={`Connect through your own ${displayName} OAuth app`}
                    steps={[
                        `Create an OAuth app in the ${displayName} console (button below).`,
                        'Give it the redirect URL shown here.',
                        'Paste its client ID and secret. Everyone on this instance connects through it, once.',
                    ]}
                >
                    <InstanceOAuthAppForm provider={provider} onSaved={instanceApp.refresh} />
                </InstanceSetupCard>
            </div>
        );
    }

    return (
        <div className="max-w-md space-y-3">
            {error && (
                <OAuthErrorPanel
                    message={error}
                    onReconnect={triggerConnect}
                    onDismiss={() => onClearError?.()}
                    isReconnecting={isThisProviderConnecting}
                    helpUrl={errorHelpUrl}
                />
            )}

            {/* Multi-account selection (Facebook pages, Supabase projects, Atlassian sites). */}
            {showPendingSelection && (
                <div className="p-3 rounded-lg bg-foreground/[0.04] border border-border space-y-2.5">
                    <div className="text-xs text-foreground/80 font-medium">
                        {provider === 'atlassian'
                            ? 'Use an available Jira site instead?'
                            : 'Select an account to connect'}
                    </div>
                    <div className="space-y-1.5">
                        {(pendingSelection?.options || []).map((option) => (
                            <button
                                key={option.id}
                                onClick={() =>
                                    onResolvePendingSelection?.(option.id)
                                }
                                disabled={isConnecting}
                                className="w-full text-left px-3 py-2 rounded-lg border border-border hover:border-foreground/20 bg-card hover:bg-accent disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                            >
                                <div className="text-sm text-foreground/90">
                                    {option.label || option.id}
                                </div>
                                {option.description && (
                                    <div className="text-[11px] text-muted-foreground mt-0.5">
                                        {option.description}
                                    </div>
                                )}
                                {provider === 'atlassian' && (
                                    <div className="text-[11px] text-blue-600 dark:text-blue-300 mt-1">
                                        Use that
                                    </div>
                                )}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Optional BYOO OAuth app (premium API users). */}
            {supportsCustomClient && (
                <div className="border border-border rounded-lg">
                    <button
                        type="button"
                        onClick={() => setShowCustomFields((v) => !v)}
                        className="w-full flex items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 hover:bg-accent transition-all rounded-lg"
                    >
                        <span className="flex items-center gap-2">
                            {showCustomFields ? (
                                <ChevronDown className="h-3.5 w-3.5" />
                            ) : (
                                <ChevronRight className="h-3.5 w-3.5" />
                            )}
                            Use custom OAuth app credentials
                        </span>
                        <span className="text-[10px] text-muted-foreground/70">
                            Optional
                        </span>
                    </button>
                    {showCustomFields && (
                        <div className="px-3 pb-3 space-y-3 border-t border-border pt-3 mt-0">
                            <div className="text-[10px] text-muted-foreground leading-relaxed space-y-2">
                                <p>
                                    By default, NoClick&apos;s OAuth app is
                                    used. If you have your own {displayName}{' '}
                                    OAuth app with premium features, enter your
                                    credentials below.
                                </p>
                                {displayedRedirectUri && (
                                    <div className="space-y-1">
                                        <span className="text-[10px] text-muted-foreground/70">Redirect URI to add in your OAuth app:</span>
                                        <code className="block w-full text-[10px] font-mono bg-foreground/[0.05] border border-border rounded px-2 py-1.5 text-foreground/70 break-all select-all">{displayedRedirectUri}</code>
                                    </div>
                                )}
                            </div>
                            <div className="space-y-1.5">
                                <span className="block text-xs text-muted-foreground">
                                    Client ID
                                </span>
                                <input
                                    type="text"
                                    value={clientId}
                                    onChange={(e) =>
                                        setClientId(e.target.value)
                                    }
                                    placeholder="Your OAuth 2.0 Client ID"
                                    className={INPUT_CLASS}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <span className="block text-xs text-muted-foreground">
                                    Client Secret
                                </span>
                                <SecretInput
                                    value={clientSecret}
                                    onChange={(e) =>
                                        setClientSecret(e.target.value)
                                    }
                                    placeholder="Your OAuth 2.0 Client Secret"
                                    inputClassName={INPUT_CLASS}
                                />
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Provider-intrinsic tenant input (Shopify store / Zendesk subdomain / Atlassian site). */}
            {connectInput && (
                <div className="space-y-1.5">
                    <span className="block text-xs text-muted-foreground">
                        {connectInput.label}
                    </span>
                    <div className="flex items-center">
                        <input
                            type="text"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            placeholder={connectInput.placeholder}
                            className={INPUT_CLASS}
                        />
                        <span className="ml-2 text-xs text-muted-foreground/70 whitespace-nowrap">
                            {connectInput.suffix}
                        </span>
                    </div>
                    {connectInput.help && (
                        <div className="text-[11px] text-muted-foreground/70">
                            {connectInput.help}
                        </div>
                    )}
                </div>
            )}

            {/* Mandatory BYOO OAuth app (e.g. Google Business Profile). */}
            {requiresCustomClient && (
                <div className="space-y-3 p-3 bg-foreground/[0.03] rounded-lg border border-border">
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                        This integration requires your own OAuth app. Create a
                        Web Application OAuth 2.0 client and add this app&apos;s
                        callback URL as an Authorised Redirect URI.
                    </p>
                    {displayedRedirectUri && (
                        <div className="space-y-1">
                            <span className="text-[10px] text-muted-foreground/70">Redirect URI to add in your OAuth app:</span>
                            <code className="block w-full text-[10px] font-mono bg-foreground/[0.05] border border-border rounded px-2 py-1.5 text-foreground/70 break-all select-all">{displayedRedirectUri}</code>
                        </div>
                    )}
                    <div className="space-y-1.5">
                        <span className="block text-xs text-muted-foreground">
                            Client ID
                        </span>
                        <input
                            type="text"
                            value={clientId}
                            onChange={(e) => setClientId(e.target.value)}
                            placeholder="123456789-abcdef.apps.googleusercontent.com"
                            className={INPUT_CLASS}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <span className="block text-xs text-muted-foreground">
                            Client Secret
                        </span>
                        <input
                            type="password"
                            value={clientSecret}
                            onChange={(e) => setClientSecret(e.target.value)}
                            placeholder="GOCSPX-..."
                            className={INPUT_CLASS}
                        />
                    </div>
                </div>
            )}

            <button
                onClick={triggerConnect}
                disabled={
                    isConnecting ||
                    showPendingSelection ||
                    inputMissing ||
                    byooMissing
                }
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium rounded-lg transition-colors bg-foreground/[0.07] text-foreground hover:bg-foreground/[0.12] disabled:bg-foreground/[0.04] disabled:text-muted-foreground disabled:cursor-not-allowed"
            >
                {isThisProviderConnecting ? (
                    <>
                        <div className="animate-spin w-4 h-4 border-2 border-foreground/30 border-t-foreground rounded-full" />
                        Connecting...
                    </>
                ) : (
                    <>
                        {/* QuickBooks/Apollo/Pipedrive brand marks are green circles; neutralize
                            them in the credentials view only (their node/canvas icon keeps the
                            brand color). */}
                        <BrandIcon
                            Icon={Icon}
                            iconColor={iconColor}
                            className={`h-4 w-4${['quickbooks', 'apollo', 'pipedrive'].includes(provider) ? ' grayscale' : ''}`}
                        />
                        {hasExistingCredential
                            ? 'Connect Another Account'
                            : `Connect ${displayName} Account`}
                    </>
                )}
            </button>

            {/* Tenant-wide admin consent: the way past Microsoft's "Need admin approval"
                wall. One admin approves NoClick for the whole directory, then the same
                popup continues into their own sign-in. */}
            {offersOrgConsent && !isThisProviderConnecting && (
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Work or school account stuck on &ldquo;Need admin approval&rdquo;? An admin can{' '}
                    <button
                        type="button"
                        onClick={triggerOrgConsent}
                        disabled={isConnecting}
                        className="underline underline-offset-2 hover:text-foreground/80 disabled:cursor-not-allowed transition-colors"
                    >
                        approve NoClick for your organization
                    </button>{' '}
                    once; after that everyone there can connect.
                </p>
            )}

            {/* Manual cancel — covers popup-close auto-detection misses (COOP blocks popup.closed). */}
            {isThisProviderConnecting && onCancel && (
                <button
                    type="button"
                    onClick={onCancel}
                    className="w-full text-xs text-muted-foreground hover:text-foreground/80 transition-colors"
                >
                    Cancel
                </button>
            )}
        </div>
    );
}
