// Redirect-OAuth ("Connect with Google/Shopify/Linear/…") on the public credential-provide
// page. It renders the SAME OAuthConnectForm the in-app UI uses — so every pre-connect input
// (Shopify store, Zendesk subdomain, Atlassian site, BYOO client id/secret, Slack user scopes)
// appears on the link too — driven by the shared provider engine (useOAuthConnect) with the
// HTTP provideLinkTransport injected via OAuthExchangeContext. Scopes / connect requirements
// come straight from the method; nothing is hand-rolled here (the Linear "Invalid scope:
// email" and the Shopify "no shop field on the link" bugs both came from a bespoke button).

import { useMemo, type ComponentType } from 'react';
import { AlertCircle } from 'lucide-react';
import { OAuthExchangeProvider } from '~/hooks/oauth/OAuthExchangeContext';
import { oauthNeedsInAppSelection } from '~/utils/oauthProviders';
import { useOAuthConnect } from '~/hooks/useOAuthConnect';
import { OAuthConnectForm } from './OAuthConnectForm';
import { provideLinkTransport } from './provideLinkTransport';

interface RedirectOAuthProvideMethodProps {
    apiBase: string;
    token: string;
    credentialType: string;
    provider: string;
    scopes: string[];
    userScopes?: string[];
    supportsCustomClient?: boolean;
    requiresCustomClient?: boolean;
    redirectUri?: string;
    serviceName: string;
    ServiceIcon: ComponentType<{ className?: string }> | null;
    onProvided: () => void;
}

// The connect form must render INSIDE the transport provider so the provider hooks'
// exchange lands on the credential-request endpoints (not the authed socket).
function ConnectForm({
    provider, credentialType, scopes, userScopes, supportsCustomClient, requiresCustomClient,
    redirectUri, serviceName, ServiceIcon, onProvided,
}: Omit<RedirectOAuthProvideMethodProps, 'apiBase' | 'token'>) {
    const {
        connect, isConnecting, connectingProvider, error, planLimitError,
        clearError, pendingSelection, resolvePendingSelection, cancelConnect,
    } = useOAuthConnect({ onCredentialCreated: () => onProvided() });

    return (
        <OAuthConnectForm
            provider={provider}
            credentialType={credentialType}
            displayName={serviceName}
            Icon={ServiceIcon || (() => null)}
            scopes={scopes}
            userScopes={userScopes}
            supportsCustomClient={supportsCustomClient}
            requiresCustomClient={requiresCustomClient}
            redirectUri={redirectUri}
            connect={connect}
            connectingProvider={connectingProvider}
            isConnecting={isConnecting}
            error={error || planLimitError}
            onClearError={clearError}
            pendingSelection={pendingSelection}
            onResolvePendingSelection={resolvePendingSelection}
            onCancel={cancelConnect}
        />
    );
}

export function RedirectOAuthProvideMethod({
    apiBase, token, credentialType, provider, scopes, userScopes,
    supportsCustomClient, requiresCustomClient, redirectUri, serviceName, ServiceIcon, onProvided,
}: RedirectOAuthProvideMethodProps) {
    const transport = useMemo(
        () => provideLinkTransport(apiBase, token, credentialType),
        [apiBase, token, credentialType],
    );
    // Some providers (Facebook/Instagram account, Supabase project) finish OAuth with an
    // in-popup selection the HTTP provide transport can't complete. Rather than let the
    // user hit a dead end mid-flow, say so up front — a sibling method (if any) stays
    // selectable, otherwise this integration must be connected inside NoClick.
    if (oauthNeedsInAppSelection(provider)) {
        // Tokenized (not zinc) so it reads correctly on BOTH surfaces — the
        // dark provide page resolves these to the same dark look.
        return (
            <div className="flex items-start gap-2.5 p-4 rounded-xl bg-foreground/[0.04] border border-border">
                <AlertCircle className="h-4 w-4 text-amber-500 dark:text-amber-400 mt-0.5 flex-shrink-0" />
                <p className="text-xs text-muted-foreground leading-relaxed">
                    {serviceName} can&apos;t be connected through a shared link — it needs an account
                    selection step inside NoClick. Please connect it from your NoClick workspace.
                </p>
            </div>
        );
    }
    return (
        <OAuthExchangeProvider value={transport}>
            <ConnectForm
                provider={provider}
                credentialType={credentialType}
                scopes={scopes}
                userScopes={userScopes}
                supportsCustomClient={supportsCustomClient}
                requiresCustomClient={requiresCustomClient}
                redirectUri={redirectUri}
                serviceName={serviceName}
                ServiceIcon={ServiceIcon}
                onProvided={onProvided}
            />
        </OAuthExchangeProvider>
    );
}
