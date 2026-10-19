// The ONE OAuth connect UI: pre-connect inputs (Shopify store, Zendesk subdomain,
// Atlassian site, BYOO client id/secret), their normalization, the multi-account
// selection step, an error, and one full-width primary that says where it goes ("Continue
// with Notion"), never greyed out: pressed before a needed input is in, it says what is
// missing. In flight it says what it waits for, with a way to cancel. It is presentational
// — the connect ENGINE (useOAuthConnect / useCredentialOAuth) is injected — so the in-app
// credential UI and the public provide link render this exact component and therefore expose
// the exact same credential mechanisms. Provider-intrinsic inputs come from the provider
// config (getOAuthConnectInput); schema-flag inputs (custom client, user scopes) are passed
// in (from the node schema in-app, from the backend method on the provide link). Added so a
// provider that needs an extra input can't work in one surface and silently break the other.

import { useEffect, useState } from 'react';
import { ArrowUpRight, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { SecretInput } from '~/components/workflow/SecretInput';
import { getOAuthConnectInput, providerSupportsOrgConsent } from '~/utils/oauthProviders';
import { getSchemaTitleFromCredentialType } from '~/utils/credentialTypes';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { inSentence } from '~/utils/credentialCopy';
import type { OAuthSelectionOption } from '~/hooks/useOAuthConnect';
import { useInstanceOAuthApp } from '~/hooks/useInstanceOAuthApp';
import { InstanceOAuthAppForm } from '~/components/credential/InstanceOAuthAppForm';
import { InstanceSetupCard } from '~/components/credential/InstanceSetupCard';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '~/components/shell/fields';
import { cn } from '~/lib/utils';

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
    scopes: string[];
    userScopes?: string[];
    /** `x-oauth-supports-custom-client`: offer an optional BYOO OAuth app. */
    supportsCustomClient?: boolean;
    /** `x-oauth-requires-custom-client`: BYOO client id/secret are mandatory. */
    requiresCustomClient?: boolean;
    /** `x-oauth-redirect-uri`: redirect URI to display when requiring a custom client. */
    redirectUri?: string;
    // --- injected engine (shared between surfaces) ---
    connect: OAuthConnectFn;
    /** Offered only when the provider supports org-wide consent; omitted = no offer. */
    connectOrgConsent?: OAuthOrgConsentFn;
    connectingProvider: string | null;
    isConnecting: boolean;
    error?: string | null;
    /** Where to fix what the error names (e.g. apply for API access). */
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
    /** The primary's words; defaults to "Continue with <displayName>". */
    connectLabel?: string;
    /** A line under the primary (where it goes, that NoClick never sees the password). */
    note?: string | null;
    /** Set while the host finishes the connect (asking the provider what the new account holds): the primary waits. */
    busyLabel?: string | null;
}

// An action inside a line of text: ink that underlines on hover, as the connect dialog's switches are.
const SHELL_INLINE = 'rounded-sm text-foreground underline-offset-4 transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

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
    scopes,
    userScopes,
    supportsCustomClient,
    requiresCustomClient,
    redirectUri,
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
    connectLabel,
    note,
    busyLabel,
}: OAuthConnectFormProps) {
    const connectInput = getOAuthConnectInput(provider, credentialType);
    // No-op on hosted: the hook reports configured without a request.
    const instanceApp = useInstanceOAuthApp(canConfigureInstanceApp ? provider : undefined);
    const [inputValue, setInputValue] = useState('');
    const [showCustomFields, setShowCustomFields] = useState(false);
    const [clientId, setClientId] = useState('');
    const [clientSecret, setClientSecret] = useState('');
    const [installationOrigin, setInstallationOrigin] = useState('');
    // Pressed before a needed input is in, the primary says what is missing rather than sitting greyed out.
    const [tried, setTried] = useState(false);

    useEffect(() => {
        setInstallationOrigin(window.location.origin);
    }, []);

    const displayedRedirectUri = resolveOAuthRedirectUri(
        redirectUri,
        installationOrigin
    );

    const isThisProviderConnecting = connectingProvider === provider;
    const waiting = isThisProviderConnecting || !!busyLabel;
    const showPendingSelection =
        pendingSelection?.provider === provider &&
        Array.isArray(pendingSelection.options) &&
        pendingSelection.options.length > 0;

    const normalizedTenant = connectInput
        ? normalizeConnectInput(inputValue, connectInput.suffix)
        : '';
    const inputMissing = connectInput ? !normalizedTenant : false;
    // Pressed before the tenant is in: said under the field it is about, which takes focus.
    const tenantMissing = tried && inputMissing && !isConnecting;
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
            if (!normalizedTenant) {
                document.getElementById(`${provider}-tenant`)?.focus();
                return;
            }
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

    const shellInput = cn(FIELD, 'font-mono placeholder:font-sans');
    const redirect = displayedRedirectUri && (
        <div>
            <span className={FIELD_LABEL}>Redirect URL for your app</span>
            <code className="block w-full select-all break-all rounded-xl bg-foreground/[0.04] px-3.5 py-2.5 font-mono text-[12.5px] text-foreground/80">{displayedRedirectUri}</code>
        </div>
    );
    const clientFields = (
        <>
            <div>
                <label className={FIELD_LABEL} htmlFor={`${provider}-client-id`}>Client ID</label>
                <input id={`${provider}-client-id`} type="text" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Your OAuth client ID" className={shellInput} autoComplete="off" spellCheck={false} />
            </div>
            <div>
                <label className={FIELD_LABEL} htmlFor={`${provider}-client-secret`}>Client secret</label>
                <SecretInput id={`${provider}-client-secret`} value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder="Your OAuth client secret" inputClassName={shellInput} autoComplete="off" />
            </div>
        </>
    );
    return (
        <div className="space-y-4">
            {error && (
                <div role="alert" className="text-[13px] leading-relaxed">
                    <p className="font-medium text-red-600 dark:text-red-400">{error.includes("didn't grant") ? 'Permissions missing' : `Couldn’t connect ${displayName}`}</p>
                    <p className="mt-1 text-foreground/80">{error}</p>
                    <p className="mt-1.5 flex flex-wrap gap-x-4">
                        {errorHelpUrl && (
                            <a href={errorHelpUrl} target="_blank" rel="noopener noreferrer" className={QUIET_LINK}>
                                How to fix it
                                <ArrowUpRight className="h-3.5 w-3.5" />
                            </a>
                        )}
                        <button type="button" onClick={() => onClearError?.()} className={QUIET_LINK}>
                            Dismiss
                        </button>
                    </p>
                </div>
            )}

            {/* Multi-account selection (Facebook pages, Supabase projects, Atlassian sites). */}
            {showPendingSelection && (
                <div>
                    <p className="mb-1 text-[13.5px] font-medium text-foreground">{provider === 'atlassian' ? 'Use an available Jira site instead?' : 'Which one should NoClick use?'}</p>
                    <div className="divide-y divide-border dark:divide-foreground/[0.07]">
                        {(pendingSelection?.options || []).map((option) => (
                            <button
                                key={option.id}
                                type="button"
                                onClick={() => onResolvePendingSelection?.(option.id)}
                                disabled={isConnecting}
                                className="group flex w-full items-center gap-3 py-2.5 text-left disabled:cursor-not-allowed disabled:opacity-60"
                            >
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[14px] text-foreground">{option.label || option.id}</span>
                                    {option.description && <span className="block truncate text-[12.5px] text-muted-foreground">{option.description}</span>}
                                </span>
                                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-colors group-hover:text-foreground" />
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Provider-intrinsic tenant input (Shopify store / Zendesk subdomain / Atlassian site). */}
            {connectInput && (
                <div>
                    <label className={FIELD_LABEL} htmlFor={`${provider}-tenant`}>{connectInput.label}</label>
                    <div className="flex items-center gap-2">
                        <input
                            id={`${provider}-tenant`}
                            type="text"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            placeholder={connectInput.placeholder}
                            className={FIELD}
                            autoComplete="off"
                            spellCheck={false}
                            aria-invalid={tenantMissing || undefined}
                            aria-describedby={tenantMissing ? `${provider}-tenant-missing` : undefined}
                        />
                        <span className="shrink-0 text-[13px] text-muted-foreground">{connectInput.suffix}</span>
                    </div>
                    {tenantMissing && (
                        <p id={`${provider}-tenant-missing`} role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
                            Enter your {inSentence(connectInput.label)}.
                        </p>
                    )}
                    {connectInput.help && <p className="mt-1.5 text-[12.5px] leading-snug text-muted-foreground">{connectInput.help}</p>}
                </div>
            )}

            {/* Mandatory BYOO OAuth app (e.g. Google Business Profile). */}
            {requiresCustomClient && (
                <div className="space-y-4">
                    <p className="text-[13px] leading-relaxed text-muted-foreground">
                        {displayName} signs in through an OAuth app of your own. Create a web application client, add the redirect URL below to it, then paste its client ID and secret.
                    </p>
                    {redirect}
                    {clientFields}
                </div>
            )}

            <button
                type="button"
                onClick={() => {
                    setTried(true);
                    triggerConnect();
                }}
                disabled={isConnecting || showPendingSelection || !!busyLabel}
                aria-busy={waiting || undefined}
                // In flight it keeps its look (dimmed, it read as dead) and says what it waits for.
                className={cn(BUTTON_PRIMARY, 'h-10 w-full justify-center', waiting && 'cursor-wait disabled:opacity-100')}
            >
                {waiting ? (
                    <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        {busyLabel ?? `Waiting for ${displayName}…`}
                    </>
                ) : (
                    connectLabel ?? `Continue with ${displayName}`
                )}
            </button>
            {note && !waiting && <p className="-mt-1.5 text-[12.5px] leading-snug text-muted-foreground">{note}</p>}
            {tried && byooMissing && !inputMissing && !isConnecting && (
                <p className="-mt-2 text-[12.5px] text-muted-foreground">Paste your OAuth app’s client ID and secret first.</p>
            )}

            {isThisProviderConnecting && onCancel && (
                <p className="-mt-1.5 text-[12.5px] leading-snug text-muted-foreground">
                    Finish in the {displayName} window.{' '}
                    <button type="button" onClick={onCancel} className={SHELL_INLINE}>
                        Cancel
                    </button>
                </p>
            )}

            {/* Tenant-wide admin consent: the way past Microsoft's "Need admin approval" wall. */}
            {offersOrgConsent && !isThisProviderConnecting && (
                <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                    Work or school account stuck on “Need admin approval”? An admin can{' '}
                    <button type="button" onClick={triggerOrgConsent} disabled={isConnecting} className={cn(SHELL_INLINE, 'disabled:cursor-not-allowed')}>
                        approve NoClick for your organization
                    </button>{' '}
                    once, then everyone there can connect.
                </p>
            )}

            {/* Optional BYOO OAuth app (premium API users). */}
            {supportsCustomClient && !requiresCustomClient && (
                <div className="space-y-4">
                    <button
                        type="button"
                        aria-expanded={showCustomFields}
                        onClick={() => setShowCustomFields((v) => !v)}
                        className="inline-flex items-center gap-1 rounded-md text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                        Use your own {displayName} OAuth app
                        <ChevronDown className={cn('h-3.5 w-3.5 transition-transform duration-200', showCustomFields && 'rotate-180')} />
                    </button>
                    {showCustomFields && (
                        <>
                            <p className="text-[12.5px] leading-relaxed text-muted-foreground">NoClick’s own app is used unless you add yours here.</p>
                            {redirect}
                            {clientFields}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
