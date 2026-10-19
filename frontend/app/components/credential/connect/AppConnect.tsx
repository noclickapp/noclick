// Connecting an app's account from inside NoClick: ConnectApp over the in-app engine. A sign-in runs the OAuth popup
// (useCredentialOAuth) and then asks the provider what the new account holds (credential:test_connection); a key goes
// through the connect seam (credential:create), whose shape check, provider proof and verdict come back with it; a
// WhatsApp number is a QR code and a phone number is bought. The Connections dialog and the node panel both draw it,
// so an account connects the same way wherever it's added.
import { Loader2 } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { ConnectApp, type ConnectAccountRow, type ConnectMethodContext, type ConnectResult, type ConnectStage } from './ConnectApp';
import { credentialRequirements, methodFromRequirement, type CredentialRequirement } from '~/components/credential/credentialMethods';
import { CredentialCreatePanel, type CredentialSaveResult } from '~/components/credential/CredentialCreatePanel';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { OAuthConnectForm } from '~/components/credential/OAuthConnectForm';
import { PhoneNumberPurchaseForm } from '~/components/credential/PhoneNumberPurchaseForm';
import { WhatsAppQRCredentialForm } from '~/components/workflow/WhatsAppQRCredentialForm';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { useCredentialOAuth, type OAuthCreatedCredential } from '~/hooks/useCredentialOAuth';
import { probeConnection } from '~/hooks/useConnectionProbe';
import { useCredentialSchemaVisible } from '~/hooks/useCredentialSchemaVisible';
import { useOrgContext } from '~/hooks/useOrgContext';
import { kindFromBackendMethod } from '~/lib/credentialMethodKind';
import { isLocalEdition } from '~/lib/edition';
import { useFeatureGate } from '~/lib/featureGates';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { PLAN_LIMITS } from '~/lib/pricing';
import { sendEventAsync } from '~/lib/socket-sender';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { invalidateCredentialsCache, isInjectedDisplayCredential } from '~/utils/credentialAutoSelect';
import { getProviderConfig } from '~/utils/oauthProviders';

/** A credential that just landed, as the hosts select or list it. */
export interface ConnectedCredential {
    id: string;
    name: string;
    credential_type: string;
}

/** Who a sign-in goes through, by the OAuth provider's own name: Gmail signs in with Google, Confluence with
 *  Confluence rather than Atlassian. */
export function oauthProviderName(method: ProvideCredentialMethod, app: string): string {
    const provider = method.oauth_provider ?? undefined;
    const config = provider === 'atlassian' && method.credential_type.startsWith('confluence') ? getProviderConfig('confluence') : getProviderConfig(provider);
    return config?.name ?? app;
}

/** The plan's per-app cap on accounts (the old plans only; Free and Member cap nothing). Over it, a connect opens the
 *  upgrade popup instead of the provider. */
function useCredentialCap(credentials: { credential_type: string; over_cap?: boolean; id: string }[], tier: string) {
    const freeMember = useFeatureGate('free_member');
    const [orgContext] = useOrgContext();
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const canCreate = useCallback(
        (credentialType: string) => {
            const cap = freeMember ? Infinity : (PLAN_LIMITS[tier as keyof typeof PLAN_LIMITS]?.credentials_per_type ?? Infinity);
            // Run-as-owner display descriptors are never the viewer's own, so they never count against the cap.
            const count = credentials.filter((c) => c.credential_type === credentialType && !c.over_cap && !isInjectedDisplayCredential(c.id)).length;
            if (count < cap) return true;
            if ((tier === 'free' || tier === 'plus') && !(orgContext.id && orgContext.role === 'member')) {
                setPlanLimitError(
                    `Plan limit reached: ${tier.charAt(0).toUpperCase() + tier.slice(1)} plan allows up to ${cap} credentials per node type (including shared). Please upgrade your plan to add more.`
                );
                return false;
            }
            return true;
        },
        [credentials, tier, freeMember, orgContext.id, orgContext.role]
    );
    return { canCreate, planLimitError, setPlanLimitError };
}

export function AppConnect({
    nodeType,
    app,
    accounts,
    onOpenAccount,
    onReconnectAccount,
    ask = true,
    showResult = true,
    onConnected,
    onStage,
    onDone,
    initialMethod,
    qrReconnectId,
    qrAutoStart = true,
}: {
    /** The node whose credential classes are the ways in ("automation-notion"). */
    nodeType: string;
    /** The app as the catalog names it. */
    app: string;
    accounts?: ConnectAccountRow[];
    onOpenAccount?: (id: string) => void;
    onReconnectAccount?: (id: string) => void;
    /** Offer asking someone else (off in surfaces that already belong to someone asking). */
    ask?: boolean;
    showResult?: boolean;
    /** Hears the account land, with what the connect-time check proved. */
    onConnected?: (credential: ConnectedCredential, verification: CredentialTestConnectionResponse | null) => void;
    onStage?: (stage: ConnectStage, result?: ConnectResult) => void;
    onDone?: () => void;
    /** The way in to open on (the kind of account being reconnected). */
    initialMethod?: string;
    /** An attached WhatsApp credential whose session died: the scan repairs it in place. */
    qrReconnectId?: string;
    /** A QR code shows unasked only when there is nothing to pick or the attached link is dead. */
    qrAutoStart?: boolean;
}) {
    const isVisible = useCredentialSchemaVisible();
    const requirements = useMemo(() => credentialRequirements(nodeType, isVisible), [nodeType, isVisible]);
    const methods = useMemo(() => requirements.map(methodFromRequirement), [requirements]);
    const requirementOf = (type: string): CredentialRequirement | undefined => requirements.find((r) => r.credential_type === type);

    // Each way in's latest context, so a sign-in that lands after a re-render reaches the dialog.
    const contexts = useRef<Record<string, ConnectMethodContext>>({});
    const [checking, setChecking] = useState<string | null>(null);
    const [validationError, setValidationError] = useState<{ message: string; helpUrl?: string } | null>(null);

    const landed = async (credentialType: string, credential: ConnectedCredential, verification: CredentialTestConnectionResponse | null, account?: string) => {
        onConnected?.(credential, verification);
        contexts.current[credentialType]?.onConnected({ credentialId: credential.id, credentialType, verification, account });
    };

    // A scanned number or a bought one is asked what it holds, as a sign-in is, so the host can show the proof.
    const landedAfterProbe = async (credentialType: string, credential: ConnectedCredential, account?: string) => {
        setChecking(credentialType);
        try {
            await landed(credentialType, credential, await probeConnection(credential.id, nodeType), account);
        } finally {
            setChecking(null);
        }
    };

    const engine = useCredentialOAuth({
        onCredentialCreated: async (credentialId: string, provider: string, credential?: OAuthCreatedCredential) => {
            const method = methods.find((m) => kindFromBackendMethod(m) === 'oauth' && m.oauth_provider === provider);
            if (!method) return;
            const created = { id: credentialId, name: credential?.name ?? app, credential_type: credential?.credential_type ?? method.credential_type };
            setChecking(method.credential_type);
            try {
                // A provider that can refuse API access after consent (Google Business Profile) is asked first.
                if (requirementOf(method.credential_type)?.schema?.['x-oauth-validates-api-access']) {
                    const access = await sendEventAsync<{ valid?: boolean; error?: string; help_url?: string }>({
                        event_name: 'credential:validate_access',
                        credential_id: credentialId,
                        node_type: nodeType,
                    }).catch(() => null);
                    if (access && !access.valid) setValidationError({ message: access.error || 'API access validation failed.', helpUrl: access.help_url });
                }
                // A sign-in proves as little as a pasted key until the provider has been asked what the account holds.
                const verification = await probeConnection(credentialId, nodeType);
                const email = credential?.metadata?.email;
                await landed(method.credential_type, created, verification, typeof email === 'string' ? email : undefined);
            } finally {
                setChecking(null);
            }
        },
    });
    const cap = useCredentialCap(engine.availableCredentials, engine.credentialTier);

    const createKey = (method: ProvideCredentialMethod) => async (name: string, data: Record<string, string>): Promise<CredentialSaveResult> => {
        if (!cap.canCreate(method.credential_type)) return null;
        try {
            const response = await sendEventAsync({
                event_name: 'credential:create',
                request_id: `create-${Date.now()}`,
                name: name || `${method.label} - ${new Date().toLocaleDateString()}`,
                credential_type: method.credential_type,
                credential_data: data,
                metadata: {},
            });
            if (response?.success && response.credential) {
                invalidateCredentialsCache();
                await engine.loadCredentials();
                await landed(method.credential_type, response.credential, response.verification ?? null);
                return null;
            }
            const message = response?.error || response?.message || 'Failed to create credential';
            if (isPlanLimitError(message)) {
                cap.setPlanLimitError(message);
                return null;
            }
            // The connect seam refused: per-field verdicts land under their inputs, a provider refusal under the form.
            return { error: message, fieldErrors: response?.field_errors ?? null, hint: response?.hint ?? null, rejected: response?.reachable === false };
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to create credential';
            if (isPlanLimitError(message)) {
                cap.setPlanLimitError(message);
                return null;
            }
            return message;
        }
    };

    const renderMethod = (method: ProvideCredentialMethod, ctx: ConnectMethodContext) => {
        contexts.current[method.credential_type] = ctx;
        const kind = kindFromBackendMethod(method);
        if (kind === 'oauth' && method.oauth_provider) {
            const provider = method.oauth_provider;
            const displayName = oauthProviderName(method, app);
            return (
                <OAuthConnectForm
                    provider={provider}
                    credentialType={method.credential_type}
                    displayName={displayName}
                    scopes={method.oauth_scopes ?? []}
                    userScopes={method.oauth_user_scopes ?? []}
                    supportsCustomClient={method.supports_custom_client}
                    requiresCustomClient={method.requires_custom_client}
                    redirectUri={method.oauth_redirect_uri ?? undefined}
                    note={ctx.note}
                    busyLabel={checking === method.credential_type ? `Checking with ${displayName}…` : null}
                    connect={engine.connect}
                    connectOrgConsent={engine.connectOrgConsent}
                    connectingProvider={engine.connectingProvider}
                    isConnecting={engine.isConnecting}
                    error={engine.error || validationError?.message}
                    errorHelpUrl={validationError?.helpUrl}
                    onClearError={() => {
                        engine.clearError();
                        setValidationError(null);
                    }}
                    pendingSelection={engine.pendingSelection}
                    onResolvePendingSelection={engine.resolvePendingSelection}
                    onCancel={engine.cancelConnect}
                    canConnect={() => cap.canCreate(method.credential_type)}
                    // Self-hosted with no OAuth app yet: ask for it right here, not in Settings.
                    canConfigureInstanceApp={isLocalEdition()}
                />
            );
        }
        // A scanned or bought number lands once the provider is asked about it; until then the form says so.
        if ((kind === 'qr_scan' || kind === 'purchase') && checking === method.credential_type) {
            return (
                <p role="status" className="flex h-10 items-center justify-center gap-2 text-[13.5px] text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {kind === 'qr_scan' ? `Checking with ${app}…` : 'Checking your new number…'}
                </p>
            );
        }
        if (kind === 'qr_scan') {
            return (
                <WhatsAppQRCredentialForm
                    credentialType={method.credential_type}
                    reconnectCredentialId={qrReconnectId}
                    autoStart={qrAutoStart}
                    onCredentialCreated={(credentialId) => {
                        void engine.loadCredentials();
                        void landedAfterProbe(method.credential_type, { id: credentialId, name: app, credential_type: method.credential_type });
                    }}
                />
            );
        }
        if (kind === 'purchase') {
            return (
                <PhoneNumberPurchaseForm
                    onCredentialCreated={(credentialId, phoneNumber) => {
                        void engine.loadCredentials();
                        void landedAfterProbe(method.credential_type, { id: credentialId, name: phoneNumber, credential_type: method.credential_type }, phoneNumber);
                    }}
                />
            );
        }
        return (
            <CredentialCreatePanel
                fields={method.credential_fields}
                app={app}
                instructions={ctx.howTo}
                showSources={ctx.showSources}
                onSave={createKey(method)}
            />
        );
    };

    return (
        <>
            <ConnectApp
                app={app}
                methods={methods}
                providerName={(m) => oauthProviderName(m, app)}
                renderMethod={renderMethod}
                accounts={accounts}
                onOpenAccount={onOpenAccount}
                onReconnectAccount={onReconnectAccount}
                ask={ask && methods[0] ? { credentialType: methods[0].credential_type } : undefined}
                showResult={showResult}
                onStage={onStage}
                onDone={onDone}
                initial={initialMethod ? { method: initialMethod } : undefined}
            />
            <UpgradePopup
                isOpen={!!cap.planLimitError || !!engine.planLimitError}
                onOpenChange={(open) => {
                    if (!open) {
                        cap.setPlanLimitError(null);
                        engine.clearError();
                    }
                }}
                errorMessage={cap.planLimitError || engine.planLimitError || ''}
            />
        </>
    );
}
