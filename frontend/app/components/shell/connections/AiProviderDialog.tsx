// Connecting an AI company, in a dialog opened from its Connections tile, through the same connect flow every app
// uses (AiConnect over ConnectApp): a switch between its subscription sign-ins and its API key, the key as two steps
// (open the company's console, then paste it), the accounts you already have with it, and asking someone who can.
// The agent node's credential panel runs the same flow, so an account added here is the one an agent picks up.
import { useCallback, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { CREDENTIALS_CHANGED_EVENT } from '~/components/shared/popups/CreateCredentialDialog';
import { connectDialogHeader, type ConnectAccountRow } from '~/components/credential/connect/ConnectApp';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { AGENT_SIGN_IN_NAMES } from '~/lib/agentCredentialModel';
import { getProviderMetadata } from '~/types/provider';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { ShellDialog } from '../ShellDialog';
import { companyAccountRow } from './accountNames';
import type { ConnectedAccount } from './accounts';
import { AiConnect, agentKeyMethod, agentSignInMethod } from './AiConnect';
import { AiMark, type AiCompany } from './aiAccounts';
import { sourceLine } from './ConnectedList';

// A sign-in here attaches to no node: the account is just added.
const NO_CREDENTIALS: Record<string, string> = {};
const attachNowhere = () => {};

/** A company's ways in: each subscription sign-in, then each provider's key. */
function companyMethods(company: AiCompany): ProvideCredentialMethod[] {
    return [
        ...company.signIns.filter((type) => type in AGENT_SIGN_IN_NAMES).map(agentSignInMethod),
        ...company.keys.map((provider) => agentKeyMethod(provider, company.keys.length > 1 ? `${getProviderMetadata(provider)?.title ?? provider} API key` : 'API key')),
    ];
}

/** An account in the company's list: what it is (its email, login or the name you gave it; else its plan or "API
 *  key") and, under it, what's wrong, whose it is, or when it was added. */
function accountRow(account: ConnectedAccount): ConnectAccountRow {
    const { title, meta: kind } = companyAccountRow(account.credential, account.line);
    return { id: account.credential.id, title, meta: [kind, sourceLine(account)].filter(Boolean).join(' · '), problem: account.problem };
}

export function AiProviderDialog({
    company,
    accounts,
    onOpenChange,
    onOpenAccount,
}: {
    /** The company to connect; null closes the dialog. */
    company: AiCompany | null;
    /** Every account you can use; the dialog lists the company's. */
    accounts: ConnectedAccount[];
    onOpenChange: (open: boolean) => void;
    onOpenAccount: (credentialId: string) => void;
}) {
    // The last company stays on screen while the dialog animates closed.
    const [shown, setShown] = useState(company);
    if (company && company !== shown) setShown(company);
    const [asking, setAsking] = useState(false);
    // An AI key has no account to show for itself, so the dialog closes on a landed one, as it always has.
    const connected = useCallback(async () => {
        if (!shown) return;
        invalidateCredentialsCache();
        window.dispatchEvent(new CustomEvent(CREDENTIALS_CHANGED_EVENT));
        toast.success(`${shown.title} connected`);
        onOpenChange(false);
    }, [shown, onOpenChange]);
    const methods = useMemo(() => (shown ? companyMethods(shown) : []), [shown]);
    const own = shown ? accounts.filter((a) => shown.credentialTypes.includes(a.credential.credential_type)) : [];
    // Asking someone reads as every connect dialog's ask does; otherwise the company's own name and what it runs.
    const header = shown && (asking ? connectDialogHeader(shown.title, 'ask') : { title: shown.title, description: shown.uses });

    return (
        <ShellDialog
            open={!!company}
            onOpenChange={(open) => {
                onOpenChange(open);
                if (!open) setAsking(false);
            }}
            title={header?.title}
            description={header?.description}
            mark={shown && <AiMark provider={shown.members[0]} size="lg" />}
            markTile={false}
            size="sm"
            testId="ai-provider-dialog"
        >
            {shown && methods.length > 0 && (
                <AiConnect
                    key={shown.id}
                    app={shown.title}
                    methods={methods}
                    credentialIds={NO_CREDENTIALS}
                    onCredentialIdsChange={attachNowhere}
                    onSignedIn={connected}
                    onKeySaved={connected}
                    accounts={own.map(accountRow)}
                    onOpenAccount={onOpenAccount}
                    ask={{ credentialType: methods[methods.length - 1].credential_type }}
                    onStage={(stage) => setAsking(stage === 'ask')}
                />
            )}
        </ShellDialog>
    );
}
