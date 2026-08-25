// The single dispatcher that turns a credential auth-method into its connect UI,
// keyed by the method's kind (api_key / oauth / agent_oauth / qr_scan). The typed
// registry below is exhaustive by construction — TS errors if a CredentialMethodKind
// has no entry — so adding a credential UI is one registry line, and the public
// provide page can't "forget" a kind (the drift that left WhatsApp QR asking users
// to type a Connection ID). Every kind component honours one uniform props contract
// and reuses the SAME engines as the in-app UI via the injected provide transport,
// so scopes / flows / binding safety can't diverge between the two surfaces.

import { useCallback, type ComponentType } from 'react';
import {
    kindFromBackendMethod,
    type CredentialMethodKind,
} from '~/lib/credentialMethodKind';
import { type CredentialField } from './CredentialFieldInput';
import { CredentialCreatePanel } from './CredentialCreatePanel';
import { RedirectOAuthProvideMethod } from './RedirectOAuthProvideMethod';
import { AgentOAuthProvideMethod } from './AgentOAuthProvideMethod';
import { provideLinkTransport } from './provideLinkTransport';
import { WhatsAppQRCredentialForm } from '~/components/workflow/WhatsAppQRCredentialForm';

// One backend auth method (from GET /credential-request/{token}). Carries method_kind
// plus everything the kind's component needs (oauth provider/scopes, fields).
export interface ProvideCredentialMethod {
    credential_type: string;
    label: string;
    /** Shown under the label in the method picker. */
    description?: string | null;
    /** "Get your API key here" deep link for the picker. */
    credential_url?: string | null;
    method_kind?: string | null;
    is_oauth: boolean;
    oauth_provider?: string | null;
    oauth_scopes?: string[];
    oauth_user_scopes?: string[];
    supports_custom_client?: boolean;
    requires_custom_client?: boolean;
    oauth_redirect_uri?: string | null;
    agent_oauth_kind?: string | null;
    credential_fields: CredentialField[];
}

// The uniform contract every kind component implements. The method carries the
// kind-specific data; the rest is the shared surface context + a single success hook.
export interface CredentialMethodConnectProps {
    method: ProvideCredentialMethod;
    apiBase: string;
    token: string;
    serviceName?: string;
    ServiceIcon: ComponentType<{ className?: string }> | null;
    onProvided: () => void;
    /** Collapse affordance for panel-style methods (api_key): renders the
     *  panel's X / Cancel. Ignored by kinds without a collapse concept. */
    onCancel?: () => void;
}

/** api_key — the app's own "New Credential" panel (shared with NodeCredentials,
 *  so this IS the drawer's create UX) persisting through the token-scoped
 *  /provide endpoint. Anonymous surfaces can't name the owner's credential,
 *  so the name field is hidden and the backend applies its default. */
function ApiKeyMethod({ method, apiBase, token, onProvided, onCancel }: CredentialMethodConnectProps) {
    const fields = method.credential_fields.length > 0
        ? method.credential_fields
        : [{
            name: 'api_key', label: 'Credential Value', type: 'password' as const,
            required: true, placeholder: 'Paste your API key or credential here',
        }];

    const save = useCallback(async (_name: string, data: Record<string, string>) => {
        try {
            const res = await fetch(`${apiBase}/api/credential-request/${token}/provide`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // Always name the chosen sibling; the backend keeps the request's own
                // type when it matches and validates against siblings otherwise.
                body: JSON.stringify({ credential_data: data, credential_type: method.credential_type }),
            });
            if (!res.ok) {
                const e = await res.json().catch(() => ({}));
                return e.detail || 'Failed to provide credential';
            }
            onProvided();
            return null;
        } catch {
            return 'Failed to submit credential. Please try again.';
        }
    }, [apiBase, token, method.credential_type, onProvided]);

    return (
        <CredentialCreatePanel
            label={method.label}
            fields={fields}
            onSave={save}
            onCancel={onCancel}
            saveLabel="Connect"
            hideName
        />
    );
}


/** oauth — the shared redirect-OAuth connect form (incl. Shopify/Zendesk/Atlassian/BYOO
 *  inputs) under the HTTP transport. */
function OAuthMethod({ method, apiBase, token, serviceName, ServiceIcon, onProvided }: CredentialMethodConnectProps) {
    if (!method.oauth_provider) return null;
    return (
        <RedirectOAuthProvideMethod
            apiBase={apiBase}
            token={token}
            credentialType={method.credential_type}
            provider={method.oauth_provider}
            scopes={method.oauth_scopes || []}
            userScopes={method.oauth_user_scopes || []}
            supportsCustomClient={method.supports_custom_client}
            requiresCustomClient={method.requires_custom_client}
            redirectUri={method.oauth_redirect_uri || undefined}
            serviceName={serviceName || method.label}
            ServiceIcon={ServiceIcon}
            onProvided={onProvided}
        />
    );
}

/** agent_oauth — the shared agent CLI sign-in components under the HTTP transport. */
function AgentOAuthMethod({ method, apiBase, token, onProvided }: CredentialMethodConnectProps) {
    return (
        <AgentOAuthProvideMethod
            apiBase={apiBase}
            token={token}
            credentialType={method.credential_type}
            onProvided={onProvided}
        />
    );
}

/** qr_scan — the same transport-aware QR form the in-app UI uses, bound to the
 *  requester through the provide transport's whatsapp:qr:* route. */
function QrScanMethod({ method, apiBase, token, onProvided }: CredentialMethodConnectProps) {
    const transport = provideLinkTransport(apiBase, token, method.credential_type);
    return (
        <WhatsAppQRCredentialForm
            credentialType={method.credential_type}
            onCredentialCreated={() => onProvided()}
            sendEvent={transport}
        />
    );
}

// kind → component. Exhaustive by the Record type: a new CredentialMethodKind won't
// compile until it has an entry here. THE one place the correspondence is declared.
const CREDENTIAL_METHOD_COMPONENTS: Record<CredentialMethodKind, ComponentType<CredentialMethodConnectProps>> = {
    api_key: ApiKeyMethod,
    oauth: OAuthMethod,
    agent_oauth: AgentOAuthMethod,
    qr_scan: QrScanMethod,
};

/** Resolve a backend method's kind (single source: kindFromBackendMethod) and render
 *  its connect component from the registry. */
export function CredentialMethodConnect(props: CredentialMethodConnectProps) {
    const kind: CredentialMethodKind = kindFromBackendMethod(props.method);
    const Component = CREDENTIAL_METHOD_COMPONENTS[kind];
    return <Component {...props} />;
}
