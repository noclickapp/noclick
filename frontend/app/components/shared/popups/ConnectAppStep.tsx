// The Connect dialog's step for one app: AppConnect over the app's accounts already connected. Loaded with the
// dialog's first open, so the pages that only mount the dialog (or read its events) don't carry the connect flow.
import { useMemo, useState } from 'react';
import { AppConnect } from '~/components/credential/connect/AppConnect';
import type { ConnectAccountRow, ConnectResult, ConnectStage } from '~/components/credential/connect/ConnectApp';
import { accountProblem, useConnectedAccounts, type ConnectedAccount } from '~/components/shell/connections/accounts';
import { INLINE_ACTION } from '~/components/workflow/CredentialRequestActions';
import { useCredentialList } from '~/hooks/useCachedCredentialList';
import { navigateToAccount } from '~/lib/navigation';
import { cn } from '~/lib/utils';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import type { ServiceCredentialOption } from '~/utils/credentialTypes';

/** Whose an account is, when it isn't simply yours. */
function whose(account: ConnectedAccount): string | undefined {
    const c = account.credential;
    if (account.source === 'shared') return `Shared by ${c.shared_by_name || c.shared_by_email || 'a teammate'}`;
    if (account.source === 'organization') return 'Your workspace';
    return undefined;
}

export default function ConnectAppStep({
    service,
    reconnect,
    onChooseAnother,
    onStage,
    onConnected,
    onClose,
}: {
    service: ServiceCredentialOption;
    /** The account being reconnected: its way in opens first. */
    reconnect?: { credentialId: string; credentialType: string };
    /** Back to the dialog's app list; absent when the dialog opened straight on this app. */
    onChooseAnother?: () => void;
    onStage: (stage: ConnectStage, result?: ConnectResult) => void;
    onConnected: () => void;
    onClose: () => void;
}) {
    const { credentials } = useCredentialList();
    const accounts = useConnectedAccounts(credentials);
    const rows = useMemo<ConnectAccountRow[]>(
        () =>
            accounts
                .filter((a) => a.service?.value === service.value)
                .map((a) => ({ id: a.credential.id, title: a.line, meta: whose(a), problem: a.problem })),
        [accounts, service.value]
    );
    // The account being reconnected: the one the dialog opened on, or one Reconnected from the list.
    const [target, setTarget] = useState(reconnect);
    const [stage, setStage] = useState<ConnectStage>('connect');
    const reconnecting = target ? credentials.find((c) => c.id === target.credentialId) : undefined;
    const qrReconnectId = reconnecting && reconnecting.connection_healthy === false && !reconnecting.revoked_at ? reconnecting.id : undefined;
    // A spare QR invites a re-scan that rebinds a working number to a new connection, so one shows unasked only when
    // no usable number exists, or to repair a dead one.
    const usableNumber = credentials.some((c) => c.credential_type === 'whatsapp_qr' && !accountProblem(c));

    return (
        <>
            <AppConnect
                key={target?.credentialId ?? ''}
                nodeType={service.value}
                app={service.label}
                accounts={rows}
                onOpenAccount={(id) => {
                    onClose();
                    navigateToAccount(id);
                }}
                onReconnectAccount={(id) => {
                    const credential = credentials.find((c) => c.id === id);
                    if (credential) setTarget({ credentialId: id, credentialType: credential.credential_type });
                }}
                initialMethod={target?.credentialType}
                qrReconnectId={qrReconnectId}
                qrAutoStart={!usableNumber || !!qrReconnectId}
                onConnected={() => {
                    invalidateCredentialsCache();
                    onConnected();
                }}
                onStage={(next, landed) => {
                    setStage(next);
                    onStage(next, landed);
                }}
                onDone={onClose}
            />
            {onChooseAnother && stage === 'connect' && (
                <button type="button" onClick={onChooseAnother} className={cn(INLINE_ACTION, '-mt-2 mb-5 block')}>
                    Choose another app
                </button>
            )}
        </>
    );
}
