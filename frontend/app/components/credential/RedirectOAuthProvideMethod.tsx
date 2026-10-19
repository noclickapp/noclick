// Redirect-OAuth ("Connect with Google/Shopify/Linear/…") on the public credential-provide
// page. It renders the SAME OAuthConnectForm the in-app UI uses — so every pre-connect input
// (Shopify store, Zendesk subdomain, Atlassian site, BYOO client id/secret, Slack user scopes)
// appears on the link too — driven by the shared provider engine (useOAuthConnect) with the
// HTTP provideLinkTransport injected via OAuthExchangeContext. Scopes / connect requirements
// come straight from the method; nothing is hand-rolled here (the Linear "Invalid scope:
// email" and the Shopify "no shop field on the link" bugs both came from a bespoke button).

import { useMemo } from 'react';
import { Info } from 'lucide-react';
import { OAuthAuthorizeProvider, OAuthExchangeProvider } from '~/hooks/oauth/OAuthExchangeContext';
import { oauthNeedsInAppSelection } from '~/utils/oauthProviders';
import { useOAuthConnect } from '~/hooks/useOAuthConnect';
import { OAuthConnectForm } from './OAuthConnectForm';
import { provideLinkTransport } from './provideLinkTransport';
import { isLocalEdition } from '~/lib/edition';

interface RedirectOAuthProvideMethodProps {
    apiBase: string;
    token: string;
    credentialType: string;
    provider: string;
    scopes: string[];
    userScopes?: string[];
    supportsCustomClient?: boolean;
    requiresCustomClient?: boolean;
    /** The requester brings its own OAuth app: the sign-in names this link so the authorize route asks consent for it. */
    oauthApp?: boolean;
    redirectUri?: string;
    serviceName: string;
    /** The line under the sign-in's button (where it goes, that NoClick never sees the password). */
    note?: string | null;
    onProvided: () => void;
    /** Told when the exchange finds the request can't be provided any more. */
    onRequestEnded?: () => void;
}

// The connect form must render INSIDE the transport provider so the provider hooks'
// exchange lands on the credential-request endpoints (not the authed socket).
function ConnectForm({
    provider, credentialType, scopes, userScopes, supportsCustomClient, requiresCustomClient,
    redirectUri, serviceName, note, onProvided,
}: Omit<RedirectOAuthProvideMethodProps, 'apiBase' | 'token' | 'oauthApp' | 'onRequestEnded'>) {
    const {
        connect, connectOrgConsent, isConnecting, connectingProvider, error, planLimitError,
        clearError, pendingSelection, resolvePendingSelection, cancelConnect,
    } = useOAuthConnect({ onCredentialCreated: () => onProvided() });

    return (
        <OAuthConnectForm
            provider={provider}
            credentialType={credentialType}
            displayName={serviceName}
            note={note}
            scopes={scopes}
            userScopes={userScopes}
            supportsCustomClient={supportsCustomClient}
            requiresCustomClient={requiresCustomClient}
            redirectUri={redirectUri}
            connect={connect}
            connectOrgConsent={connectOrgConsent}
            connectingProvider={connectingProvider}
            isConnecting={isConnecting}
            error={error || planLimitError}
            onClearError={clearError}
            pendingSelection={pendingSelection}
            onResolvePendingSelection={resolvePendingSelection}
            onCancel={cancelConnect}
            canConfigureInstanceApp={isLocalEdition()}
        />
    );
}

export function RedirectOAuthProvideMethod({
    apiBase, token, credentialType, provider, scopes, userScopes,
    supportsCustomClient, requiresCustomClient, oauthApp, redirectUri, serviceName, note, onProvided, onRequestEnded,
}: RedirectOAuthProvideMethodProps) {
    const transport = useMemo(
        () => provideLinkTransport(apiBase, token, credentialType, onRequestEnded),
        [apiBase, token, credentialType, onRequestEnded],
    );
    const authorizeParams = useMemo(() => {
        const params: Record<string, string> = {};
        if (oauthApp) params.oauth_app = token;
        return params;
    }, [oauthApp, token]);
    // Some providers (Facebook/Instagram account, Supabase project) finish OAuth with an
    // in-popup selection the HTTP provide transport can't complete. Rather than let the
    // user hit a dead end mid-flow, say so up front — a sibling method (if any) stays
    // selectable, otherwise this integration must be connected inside NoClick.
    if (oauthNeedsInAppSelection(provider)) {
        return (
            <p className="flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground">
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                {serviceName} can’t be connected through a shared link: signing in asks which account to use, a step that
                only runs inside NoClick. Connect it from a NoClick workspace instead.
            </p>
        );
    }
    return (
        <OAuthExchangeProvider value={transport}>
            <OAuthAuthorizeProvider value={authorizeParams}>
                <ConnectForm
                    provider={provider}
                    credentialType={credentialType}
                    scopes={scopes}
                    userScopes={userScopes}
                    supportsCustomClient={supportsCustomClient}
                    requiresCustomClient={requiresCustomClient}
                    redirectUri={redirectUri}
                    serviceName={serviceName}
                    note={note}
                    onProvided={onProvided}
                />
            </OAuthAuthorizeProvider>
        </OAuthExchangeProvider>
    );
}
