// Connecting an AI account through the flow every app uses (ConnectApp): a switch between its subscription sign-ins
// and its API key, the key as two steps (open the company's console, then paste it), the accounts you already have.
// Connections' company dialog (AiProviderDialog) and the agent node's credential panel (AgentCredentialsForm, which
// the Setup step, the chat's setup and build cards and the builder's asks all draw) run it, so an AI account connects
// the same way wherever it's added; a provide link runs it too, over the link's own calls (`via`).
import { useMemo, useState, type ReactNode } from 'react';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { AgentOAuthConnect, type AgentOAuthComponentProps } from '~/components/workflow/AgentOAuthConnect';
import { ConnectApp, type ConnectAccountRow, type ConnectStage } from '~/components/credential/connect/ConnectApp';
import { CredentialCreatePanel, saveRefusal, type CredentialSaveResult } from '~/components/credential/CredentialCreatePanel';
import type { CredentialField } from '~/components/credential/CredentialFieldInput';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import type { AskSignIn } from '~/components/workflow/CredentialRequestActions';
import { createAgentKey, getFieldLabel, getPlaceholder, shouldMaskField, type CreatedAgentCredential } from '~/hooks/useAgentApiKey';
import { AGENT_SIGN_IN_NAMES, getAgentCredentialType } from '~/lib/agentCredentialModel';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { cn } from '~/lib/utils';
import { getProviderMetadata, type ModelProvider } from '~/types/provider';
import { getCredentialIcon } from '~/utils/credentialIcons';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { BUTTON_PRIMARY } from '../buttons';
import type { AiCompany } from './aiAccounts';

/** A subscription sign-in as a way in ("Claude plan"). */
export function agentSignInMethod(type: string): ProvideCredentialMethod {
    return {
        credential_type: type,
        label: `${AGENT_SIGN_IN_NAMES[type].subscription} plan`,
        method_kind: 'agent_oauth',
        agent_oauth_kind: type,
        is_oauth: false,
        credential_fields: [],
    };
}

/** A provider's API key as a way in: its required values, and its console as where to get one. */
export function agentKeyMethod(provider: ModelProvider, label = 'API key'): ProvideCredentialMethod {
    const metadata = getProviderMetadata(provider);
    const keys = metadata?.requiredApiKeys?.[0] ?? [];
    const fields: CredentialField[] = keys.map((envVar) => ({
        name: envVar,
        label: keys.length === 1 ? 'API key' : getFieldLabel(envVar),
        type: shouldMaskField(envVar) ? 'password' : 'text',
        required: true,
        placeholder: keys.length === 1 ? undefined : getPlaceholder(envVar),
    }));
    return {
        credential_type: getAgentCredentialType(provider),
        label,
        method_kind: 'api_key',
        is_oauth: false,
        credential_url: metadata?.providerURL ?? null,
        credential_fields: fields,
    };
}

/** The provider a key method saves as. */
const keyProvider = (method: ProvideCredentialMethod) => method.credential_type.replace(/^agent_/, '') as ModelProvider;

/** A company's ways in: each subscription sign-in, then each provider's key. */
export function companyMethods(company: AiCompany): ProvideCredentialMethod[] {
    return [
        ...company.signIns.filter((type) => type in AGENT_SIGN_IN_NAMES).map(agentSignInMethod),
        ...company.keys.map((provider) => agentKeyMethod(provider, company.keys.length > 1 ? `${getProviderMetadata(provider)?.title ?? provider} API key` : 'API key')),
    ];
}

type SendEvent = NonNullable<AgentOAuthComponentProps['sendEvent']>;

/** A key's save, as the socket's `credential:create` replies to it. */
interface KeyReply {
    success?: boolean;
    credential?: CreatedAgentCredential | null;
    verification?: CredentialTestConnectionResponse | null;
    error?: string | null;
    message?: string | null;
    field_errors?: Record<string, string> | null;
    hint?: string | null;
    reachable?: boolean | null;
}

/** A host that connects through something other than the signed-in app's socket (a provide link): where a sign-in's
 *  calls go, how a key is saved, and the line under a key's form. Keep it stable across renders. */
export interface AiConnectVia {
    signIn: (credentialType: string) => SendEvent;
    saveKey: (method: ProvideCredentialMethod, values: Record<string, string>) => Promise<KeyReply>;
    keyNote?: ReactNode;
}

/** A company's ways in: each subscription sign-in, then each provider's key; only the one whose credential type is
 *  `only`, where given. */
export function companyMethods(company: AiCompany, only?: string): ProvideCredentialMethod[] {
    const all = [
        ...company.signIns.filter((type) => type in AGENT_SIGN_IN_NAMES).map(agentSignInMethod),
        ...company.keys.map((provider) => agentKeyMethod(provider, company.keys.length > 1 ? `${getProviderMetadata(provider)?.title ?? provider} API key` : 'API key')),
    ];
    return only ? all.filter((m) => m.credential_type === only) : all;
}

type SendEvent = NonNullable<AgentOAuthComponentProps['sendEvent']>;

/** A key's save, as the socket's `credential:create` replies to it. */
interface KeyReply {
    success?: boolean;
    credential?: CreatedAgentCredential | null;
    verification?: CredentialTestConnectionResponse | null;
    error?: string | null;
    message?: string | null;
    field_errors?: Record<string, string> | null;
    hint?: string | null;
    reachable?: boolean | null;
}

/** A host that connects through something other than the signed-in app's socket (a provide link): where a sign-in's
 *  calls go, how a key is saved, and the line under a key's form. Keep it stable across renders. */
export interface AiConnectVia {
    signIn: (credentialType: string) => SendEvent;
    saveKey: (method: ProvideCredentialMethod, values: Record<string, string>) => Promise<KeyReply>;
    keyNote?: ReactNode;
}

/** A subscription sign-in: one button that says whose sign-in it opens, the sign-in's own note under it; pressed, the
 *  sign-in's own flow (a device code, a pasted code) runs in its place. */
function SignIn({
    type,
    credentialIds,
    onCredentialIdsChange,
    onSignedIn,
    via,
}: {
    type: string;
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (ids: Record<string, string>) => void;
    onSignedIn: () => Promise<void>;
    via?: AiConnectVia;
}) {
    const names = AGENT_SIGN_IN_NAMES[type];
    const sendEvent = useMemo(() => via?.signIn(type), [via, type]);
    return (
        <div data-testid={`sign-in-${type}`}>
            <AgentOAuthConnect
                credentialType={type}
                credentialIds={credentialIds}
                onCredentialIdsChange={onCredentialIdsChange}
                onCredentialCreated={onSignedIn}
                sendEvent={sendEvent}
                renderStart={(start, note) => (
                    <div className="space-y-2.5">
                        <PlanSignInButton type={type} label={`Sign in with ${names.signInWith}`} onClick={start} />
                        <p className="text-[12.5px] leading-snug text-muted-foreground">{note}</p>
                    </div>
                )}
            />
        </div>
    );
}

export function AiConnect({
    app,
    methods,
    credentialIds,
    onCredentialIdsChange,
    onSignedIn,
    onKeySaved,
    accounts,
    onOpenAccount,
    ask,
    onStage,
    via,
}: {
    /** Who the account is with, as the flow names it ("Anthropic"). */
    app: string;
    /** Its ways in: sign-ins (agentSignInMethod) before keys (agentKeyMethod). */
    methods: ProvideCredentialMethod[];
    /** What a sign-in replaces or attaches to (a node's map; nothing for an account that's only added). */
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (ids: Record<string, string>) => void;
    onSignedIn: () => Promise<void>;
    onKeySaved: (credential: CreatedAgentCredential, verification: CredentialTestConnectionResponse | null) => Promise<void>;
    accounts?: ConnectAccountRow[];
    onOpenAccount?: (id: string) => void;
    /** Offer asking someone who can (the credential type the request names, and the sign-in its link offers). */
    ask?: { credentialType: string; signIn?: AskSignIn };
    onStage?: (stage: ConnectStage) => void;
    /** Connect over a provide link's calls instead of the signed-in app's socket. */
    via?: AiConnectVia;
}) {
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);

    const saveKey = (method: ProvideCredentialMethod) => async (name: string, data: Record<string, string>): Promise<CredentialSaveResult> => {
        try {
            const response: KeyReply = via ? await via.saveKey(method, data) : await createAgentKey(keyProvider(method), data, name);
            if (response?.success && response.credential) {
                await onKeySaved(response.credential, response.verification ?? null);
                return null;
            }
            const message = response?.error || response?.message || 'Failed to create credential';
            if (!via && isPlanLimitError(message)) {
                setPlanLimitError(message);
                return null;
            }
            // The provider's key probe refused it: its words, under who refused; per-field verdicts under their inputs.
            return saveRefusal({ ...response, error: message });
        } catch (err) {
            return err instanceof Error ? err.message : 'Failed to create credential';
        }
    };

    return (
        <>
            <ConnectApp
                app={app}
                methods={methods}
                renderMethod={(method, ctx) =>
                    method.agent_oauth_kind ? (
                        <SignIn type={method.agent_oauth_kind} credentialIds={credentialIds} onCredentialIdsChange={onCredentialIdsChange} onSignedIn={onSignedIn} via={via} />
                    ) : (
                        <>
                            <CredentialCreatePanel fields={method.credential_fields} app={app} instructions={ctx.howTo} showSources={ctx.showSources} onSave={saveKey(method)} />
                            {via?.keyNote}
                        </>
                    )
                }
                accounts={accounts}
                onOpenAccount={onOpenAccount}
                ask={ask}
                // The host shows what landed: the dialog closes on it, the node panel selects it.
                showResult={false}
                onStage={onStage}
            />
            {/* A plan's limits are the signed-in account's; a link's visitor has none. */}
            {!via && (
                <UpgradePopup
                    isOpen={!!planLimitError}
                    onOpenChange={(open) => {
                        if (!open) setPlanLimitError(null);
                    }}
                    errorMessage={planLimitError || ''}
                />
            )}
        </>
    );
}
