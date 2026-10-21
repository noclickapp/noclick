// The one credential-delete confirmation: dry-runs the delete to name the
// workflows still using the credential and what else holds it, confirms
// through the shared DeleteConfirmPopup, then deletes and clears every
// credentials cache. Lifted out of Settings so the Dashboard's credential
// pills (and any future surface) confirm and delete exactly the way Settings does.
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { sendEventAsync } from '~/lib/socket-sender';
import { invalidateCredentialsCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import type { CredentialAffectedHolder, CredentialAffectedWorkflow } from '~/types/socket-events.generated';

export interface DeletableCredential {
    id: string;
    name: string;
}

interface Affected {
    workflows: CredentialAffectedWorkflow[];
    holders: CredentialAffectedHolder[];
}

const NOTHING: Affected = { workflows: [], holders: [] };

function holderLabel(holder: CredentialAffectedHolder): string {
    const usedBy = holder.used_by?.length ? ` (used by ${holder.used_by.join(', ')})` : '';
    return `the ${holder.kind} "${holder.name}"${usedBy}`;
}

/** The warning the dialog shows once the dry run names the dependants. */
export function credentialDeleteMessage(
    name: string,
    affected: CredentialAffectedWorkflow[],
    holders: CredentialAffectedHolder[],
): string | undefined {
    const lines: string[] = [];
    if (affected.length) {
        const names = affected.slice(0, 5).map((w) => w.workflow_name).join(', ');
        lines.push(
            `"${name}" is used by ${affected.length} workflow${affected.length === 1 ? '' : 's'}: ${names}${affected.length > 5 ? ', …' : ''}. Deleting it will deactivate their triggers and break those nodes until you connect a new credential.`,
        );
    }
    if (holders.length) {
        const labels = holders.map(holderLabel);
        const listed = labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
        lines.push(`Deleting "${name}" also disconnects ${listed} until it's reconnected.`);
    }
    return lines.length ? lines.join(' ') : undefined;
}

export function CredentialDeleteDialog({ credential, onClose, onDeleted }: { credential: DeletableCredential | null; onClose: () => void; onDeleted?: () => void }) {
    const [affected, setAffected] = useState<Affected>(NOTHING);

    // Dry-run while the dialog is open: the backend lists the workflows and
    // whatever else still holds the credential, without deleting anything.
    useEffect(() => {
        setAffected(NOTHING);
        if (!credential) return;
        let cancelled = false;
        sendEventAsync({
            event_name: 'credential:delete',
            request_id: `delete-cred-dryrun-${Date.now()}`,
            credential_id: credential.id,
            confirm: false,
        })
            .then((response) => {
                if (!cancelled && response?.success) {
                    setAffected({ workflows: response.affected_workflows ?? [], holders: response.affected_holders ?? [] });
                }
            })
            .catch(() => {
                // Non-fatal: the dialog shows the generic warning instead.
            });
        return () => {
            cancelled = true;
        };
    }, [credential]);

    const confirm = useCallback(async () => {
        if (!credential) return;
        try {
            const response = await sendEventAsync({
                event_name: 'credential:delete',
                request_id: `delete-cred-${Date.now()}`,
                credential_id: credential.id,
                confirm: true,
            });
            if (response?.success) {
                invalidateCredentialsCache();
                removeCredentialsFromCache([credential.id]);
                toast.success('Credential deleted');
                onDeleted?.();
            } else {
                // The reason rides `error`; `message` is only set on success.
                toast.error(response?.error || 'Failed to delete credential');
            }
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to delete credential');
        } finally {
            onClose();
        }
    }, [credential, onClose, onDeleted]);

    return (
        <DeleteConfirmPopup
            itemType="Credential"
            itemName={credential?.name}
            isOpen={!!credential}
            onOpenChange={(open) => {
                if (!open) onClose();
            }}
            onConfirmDelete={confirm}
            customMessage={credential ? credentialDeleteMessage(credential.name, affected.workflows, affected.holders) : undefined}
        />
    );
}
