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
import { CredentialCreatePanel, saveRefusal, type CredentialSaveResult } from './CredentialCreatePanel';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { RedirectOAuthProvideMethod } from './RedirectOAuthProvideMethod';
import { AgentOAuthProvideMethod } from './AgentOAuthProvideMethod';
import { provideLinkTransport, requestEnded } from './provideLinkTransport';
import { useProvideExchangeStandIn } from '~/hooks/oauth/OAuthExchangeContext';
import { WhatsAppQRCredentialForm } from '~/components/workflow/WhatsAppQRCredentialForm';
import { McpConnectForm } from './McpConnectForm';
import { KeySteps } from './connect/ConnectApp';
import { copyMethodOf, howToGet, methodLine } from '~/utils/credentialCopy';

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
    /** The requester brings its own OAuth app for this provider: the sign-in asks consent for it. */
    oauth_app?: boolean;
    agent_oauth_kind?: string | null;
    credential_fields: CredentialField[];
    /** A vendor MCP way in (kind `mcp`): the server it connects through. */
    mcp_server?: string | null;
}

// The uniform contract every kind component implements. The method carries the
// kind-specific data; the rest is the shared surface context + a single success hook.
export interface CredentialMethodConnectProps {
    method: ProvideCredentialMethod;
    apiBase: string;
    token: string;
    serviceName?: string;
    /** Fires once the credential lands. Manual credentials carry what the
     *  connect-time probe proved, so the success state can show it. */
    onProvided: (verification?: CredentialTestConnectionResponse | null) => void;
    /** Told when a save finds the request can't be provided any more (a newer
     *  request replaced it, it ended, or it ran out of tries). */
    onRequestEnded?: () => void;
    /** The connect dialog's context for this way in (ConnectApp): the steps it shows above the form, whether each
     *  field links where its value comes from, and the line under a sign-in's button. */
    howTo?: string | null;
    showSources?: boolean;
    note?: string | null;
    /** Draw a key as its numbered steps itself, for a surface that shows one way in outside the connect flow (the
     *  coordinator's connect card); inside it, the flow draws them. */
    steps?: boolean;
}

/** What a provide link's /provide answered for typed-in values, in the socket's `credential:create` reply shape, so
 *  every key form reads a refusal the same way. */
export interface ProvidedKey {
    success: boolean;
    credential_id?: string;
    verification?: CredentialTestConnectionResponse | null;
    error?: string;
    field_errors?: Record<string, string> | null;
    hint?: string | null;
    reachable?: boolean | null;
}

/** Send typed-in values through a provide link, as `credentialType` (the request's own, or a sibling it offers). */
export async function provideKey(
    apiBase: string,
    token: string,
    credentialType: string,
    data: Record<string, string>,
    onRequestEnded?: () => void,
): Promise<ProvidedKey> {
    const url = `${apiBase}/api/credential-request/${token}/provide`;
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential_data: data, credential_type: credentialType }),
    });
    if (!res.ok) {
        if (requestEnded(res, url)) onRequestEnded?.();
        // The connect seam refuses with {message, field_errors, hint}; older/other errors are a plain detail string.
        const detail = (await res.json().catch(() => ({}))).detail;
        if (detail && typeof detail === 'object') {
            return { success: false, error: detail.message || 'Failed to provide credential', field_errors: detail.field_errors ?? null, hint: detail.hint ?? null, reachable: detail.reachable };
        }
        return { success: false, error: detail || 'Failed to provide credential' };
    }
    const body = await res.json().catch(() => ({}));
    return { success: true, credential_id: body?.credential_id, verification: body?.verification ?? null };
}

/** api_key — the connect form the in-app UI uses (CredentialCreatePanel) persisting through the token-scoped
 *  /provide endpoint. Anonymous surfaces can't name the owner's credential; the backend applies its default name. */
function ApiKeyMethod({ method, apiBase, token, serviceName, onProvided, onRequestEnded, howTo, showSources = true, steps = false }: CredentialMethodConnectProps) {
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
            // Always name the chosen sibling; the backend keeps the request's own type when it matches and validates
            // against siblings otherwise.
            const response = await provideKey(apiBase, token, method.credential_type, data, onRequestEnded);
            if (!response.success) return saveRefusal(response);
            onProvided(response.verification ?? null);
            return null;
        } catch {
            return 'Failed to submit credential. Please try again.';
        }
    }, [apiBase, token, method.credential_type, onProvided, onRequestEnded]);

    const app = serviceName ?? method.label;
    const form = (
        <CredentialCreatePanel
            fields={fields}
            onSave={save}
            app={app}
            instructions={howTo ?? (steps ? howToGet(copyMethodOf(method), app) : method.instructions)}
            showSources={steps ? false : showSources}
        />
    );
    return steps ? (
        <KeySteps method={method} app={app}>
            {form}
        </KeySteps>
    ) : (
        form
    );
}


/** oauth — the shared redirect-OAuth connect form (incl. Shopify/Zendesk/Atlassian/BYOO
 *  inputs) under the HTTP transport. */
function OAuthMethod({ method, apiBase, token, serviceName, onProvided, onRequestEnded, note }: CredentialMethodConnectProps) {
    if (!method.oauth_provider) {
        // The server names every sign-in's provider; one without has nothing to open, so say so rather than show nothing.
        console.error(`[credential-provide] ${method.credential_type} is a sign-in with no provider`);
        return (
            <p className="text-[13px] leading-relaxed text-muted-foreground">
                {serviceName || method.label} can’t be connected through this link. Ask whoever sent it for a new one.
            </p>
        );
    }
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
            oauthApp={method.oauth_app}
            redirectUri={method.oauth_redirect_uri || undefined}
            serviceName={serviceName || method.label}
            note={note}
            onProvided={onProvided}
            onRequestEnded={onRequestEnded}
        />
    );
}

/** agent_oauth — the shared agent CLI sign-in components under the HTTP transport. */
function AgentOAuthMethod({ method, apiBase, token, onProvided, onRequestEnded }: CredentialMethodConnectProps) {
    return (
        <AgentOAuthProvideMethod
            apiBase={apiBase}
            token={token}
            credentialType={method.credential_type}
            onProvided={onProvided}
            onRequestEnded={onRequestEnded}
        />
    );
}

/** qr_scan — the same transport-aware QR form the in-app UI uses, bound to the
 *  requester through the provide transport's whatsapp:qr:* route (a demo's own
 *  answers where a demo stands in). */
function QrScanMethod({ method, apiBase, token, onProvided, onRequestEnded }: CredentialMethodConnectProps) {
    const standIn = useProvideExchangeStandIn();
    const transport = standIn ?? provideLinkTransport(apiBase, token, method.credential_type, onRequestEnded);
    return (
        <WhatsAppQRCredentialForm
            credentialType={method.credential_type}
            onCredentialCreated={() => onProvided()}
            sendEvent={transport}
        />
    );
}

/** mcp — the integration's own MCP server, signed into through the link's HTTP transport. */
function McpMethod({ method, apiBase, token, serviceName, onProvided, onRequestEnded, note }: CredentialMethodConnectProps) {
    const transport = provideLinkTransport(apiBase, token, method.credential_type, onRequestEnded);
    const app = serviceName || method.label;
    return (
        <McpConnectForm
            credentialType={method.credential_type}
            app={app}
            note={note ?? methodLine(copyMethodOf(method), app)}
            sendEvent={transport}
            onConnected={(_credential, verification) => onProvided(verification)}
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
    mcp: McpMethod,
};

/** Resolve a backend method's kind (single source: kindFromBackendMethod) and render
 *  its connect component from the registry. */
export function CredentialMethodConnect(props: CredentialMethodConnectProps) {
    const kind: CredentialMethodKind = kindFromBackendMethod(props.method);
    const Component = CREDENTIAL_METHOD_COMPONENTS[kind];
    return <Component {...props} />;
}
