// Connecting an AI account through the flow every app uses (ConnectApp): a switch between its subscription sign-ins
// and its API key, the key as two steps (open the company's console, then paste it), the accounts you already have.
// Connections' company dialog (AiProviderDialog) and the agent node's credential panel (AgentCredentialsForm, which
// the Setup step, the chat's setup and build cards and the builder's asks all draw) run it, so an AI account connects
// the same way wherever it's added.
import { useState } from 'react';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { AgentOAuthConnect } from '~/components/workflow/AgentOAuthConnect';
import { ConnectApp, type ConnectAccountRow, type ConnectStage } from '~/components/credential/connect/ConnectApp';
import { CredentialCreatePanel, type CredentialSaveResult } from '~/components/credential/CredentialCreatePanel';
import type { CredentialField } from '~/components/credential/CredentialFieldInput';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { createAgentKey, getFieldLabel, getPlaceholder, shouldMaskField, type CreatedAgentCredential } from '~/hooks/useAgentApiKey';
import { AGENT_SIGN_IN_NAMES, getAgentCredentialType } from '~/lib/agentCredentialModel';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { cn } from '~/lib/utils';
import { getProviderMetadata, type ModelProvider } from '~/types/provider';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { BUTTON_PRIMARY } from '../buttons';

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

/** A subscription sign-in: one button that says whose sign-in it opens, the sign-in's own note under it; pressed, the
 *  sign-in's own flow (a device code, a pasted code) runs in its place. */
function SignIn({
    type,
    credentialIds,
    onCredentialIdsChange,
    onSignedIn,
}: {
    type: string;
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (ids: Record<string, string>) => void;
    onSignedIn: () => Promise<void>;
}) {
    const names = AGENT_SIGN_IN_NAMES[type];
    return (
        <div data-testid={`sign-in-${type}`}>
            <AgentOAuthConnect
                credentialType={type}
                credentialIds={credentialIds}
                onCredentialIdsChange={onCredentialIdsChange}
                onCredentialCreated={onSignedIn}
                renderStart={(start, note) => (
                    <div className="space-y-2.5">
                        <button type="button" onClick={start} className={cn(BUTTON_PRIMARY, 'h-10 w-full justify-center')}>
                            Sign in with {names.signInWith}
                        </button>
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
    /** Offer asking someone who can (the credential type the request names). */
    ask?: { credentialType: string };
    onStage?: (stage: ConnectStage) => void;
}) {
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);

    const saveKey = (provider: ModelProvider) => async (name: string, data: Record<string, string>): Promise<CredentialSaveResult> => {
        try {
            const response = await createAgentKey(provider, data, name);
            if (response?.success && response.credential) {
                await onKeySaved(response.credential as CreatedAgentCredential, response.verification ?? null);
                return null;
            }
            const message = response?.error || response?.message || 'Failed to create credential';
            if (isPlanLimitError(message)) {
                setPlanLimitError(message);
                return null;
            }
            // The provider's key probe refused it: its words, under who refused. Anything else is a plain error.
            return { error: message, rejected: response?.reachable === false };
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
                        <SignIn type={method.agent_oauth_kind} credentialIds={credentialIds} onCredentialIdsChange={onCredentialIdsChange} onSignedIn={onSignedIn} />
                    ) : (
                        <CredentialCreatePanel fields={method.credential_fields} app={app} instructions={ctx.howTo} showSources={ctx.showSources} onSave={saveKey(keyProvider(method))} />
                    )
                }
                accounts={accounts}
                onOpenAccount={onOpenAccount}
                ask={ask}
                // The host shows what landed: the dialog closes on it, the node panel selects it.
                showResult={false}
                onStage={onStage}
            />
            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => {
                    if (!open) setPlanLimitError(null);
                }}
                errorMessage={planLimitError || ''}
            />
        </>
    );
}
