// The single dispatcher that turns a credential auth-method into its connect UI,
// keyed by the method's kind (api_key / oauth / agent_oauth / qr_scan). The typed
// registry below is exhaustive by construction — TS errors if a CredentialMethodKind
// has no entry — so adding a credential UI is one registry line, and the public
// provide page can't "forget" a kind (the drift that left WhatsApp QR asking users
// to type a Connection ID). Every kind component honours one uniform props contract
// and reuses the SAME engines as the in-app UI via the injected provide transport,
// so scopes / flows / binding safety can't diverge between the two surfaces.

import { useCallback, type ComponentType } from 'react';
import { Link, useLocation } from 'react-router';
import { Button } from '~/components/ui/button';
import {
    kindFromBackendMethod,
    type CredentialMethodKind,
} from '~/lib/credentialMethodKind';
import { type CredentialField } from './CredentialFieldInput';
import { CredentialCreatePanel, type CredentialSaveResult } from './CredentialCreatePanel';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
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
    /** Where the values come from, in steps (the schema's x-credential-instructions). */
    instructions?: string | null;
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
    /** Fires once the credential lands. Manual credentials carry what the
     *  connect-time probe proved, so the success state can show it. */
    onProvided: (verification?: CredentialTestConnectionResponse | null) => void;
    /** Collapse affordance for panel-style methods (api_key): renders the
     *  panel's X / Cancel. Ignored by kinds without a collapse concept. */
    onCancel?: () => void;
}

/** api_key — the app's own "New Credential" panel (shared with NodeCredentials,
 *  so this IS the drawer's create UX) persisting through the token-scoped
 *  /provide endpoint. Anonymous surfaces can't name the owner's credential,
 *  so the name field is hidden and the backend applies its default. */
function ApiKeyMethod({ method, apiBase, token, onProvided, onCancel }: CredentialMethodConnectProps) {
    // The wire shape is snake_case; the shared field renderer speaks camelCase.
    const fields: CredentialField[] = method.credential_fields.length > 0
        ? method.credential_fields.map((f) => ({
            ...f,
            helpUrl: f.helpUrl ?? (f as { help_url?: string | null }).help_url ?? null,
        }))
        : [{
            name: 'api_key', label: 'Credential Value', type: 'password' as const,
            required: true, placeholder: 'Paste your API key or credential here',
        }];

    const save = useCallback(async (_name: string, data: Record<string, string>): Promise<CredentialSaveResult> => {
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
                // The connect seam refuses with {message, field_errors, hint};
                // older/other errors are a plain detail string.
                const detail = e.detail;
                if (detail && typeof detail === 'object') {
                    return {
                        error: detail.message || 'Failed to provide credential',
                        fieldErrors: detail.field_errors ?? null,
                        hint: detail.hint ?? null,
                    };
                }
                return detail || 'Failed to provide credential';
            }
            const body = await res.json().catch(() => ({}));
            onProvided(body?.verification ?? null);
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
            instructions={method.instructions}
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

/** A public credential link leads to an authenticated owner confirmation page.
 *  The owner returns here afterward so the existing builder answer can resume. */
function PurchaseMethod({ token }: CredentialMethodConnectProps) {
    const location = useLocation();
    const returnTo = location.pathname + location.search;
    return (
        <div className="space-y-3">
            <p className="text-sm leading-relaxed text-muted-foreground">The account owner can choose a number and review its monthly cost before purchasing.</p>
            <Button asChild variant="secondary"><Link to={`/credential/purchase/${token}?return_to=${encodeURIComponent(returnTo)}`}>Review phone number</Link></Button>
        </div>
    );
}

// kind → component. Exhaustive by the Record type: a new CredentialMethodKind won't
// compile until it has an entry here. THE one place the correspondence is declared.
const CREDENTIAL_METHOD_COMPONENTS: Record<CredentialMethodKind, ComponentType<CredentialMethodConnectProps>> = {
    api_key: ApiKeyMethod,
    oauth: OAuthMethod,
    agent_oauth: AgentOAuthMethod,
    qr_scan: QrScanMethod,
    purchase: PurchaseMethod,
};

/** Resolve a backend method's kind (single source: kindFromBackendMethod) and render
 *  its connect component from the registry. */
export function CredentialMethodConnect(props: CredentialMethodConnectProps) {
    const kind: CredentialMethodKind = kindFromBackendMethod(props.method);
    const Component = CREDENTIAL_METHOD_COMPONENTS[kind];
    return <Component {...props} />;
}
