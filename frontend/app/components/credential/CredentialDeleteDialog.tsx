// The one credential-delete confirmation: dry-runs the delete to name the
// workflows still using the credential, confirms through the shared
// DeleteConfirmPopup, then deletes and clears every credentials cache. Lifted
// out of Settings so the Dashboard's credential pills (and any future surface)
// confirm and delete exactly the way Settings does.
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { sendEventAsync } from '~/lib/socket-sender';
import { invalidateCredentialsCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';

export interface DeletableCredential {
    id: string;
    name: string;
}

interface AffectedWorkflow {
    workflow_id: string;
    workflow_name: string;
}

/** The warning the dialog shows once the dry run names the dependants. */
export function credentialDeleteMessage(name: string, affected: AffectedWorkflow[]): string | undefined {
    if (!affected.length) return undefined;
    const names = affected.slice(0, 5).map((w) => w.workflow_name).join(', ');
    return `"${name}" is used by ${affected.length} workflow${affected.length === 1 ? '' : 's'}: ${names}${affected.length > 5 ? ', …' : ''}. Deleting it will deactivate their triggers and break those nodes until you connect a new credential.`;
}

export function CredentialDeleteDialog({ credential, onClose, onDeleted }: { credential: DeletableCredential | null; onClose: () => void; onDeleted?: () => void }) {
    const [affected, setAffected] = useState<AffectedWorkflow[]>([]);

    // Dry-run while the dialog is open: the backend lists the workflows still
    // referencing the credential without deleting anything.
    useEffect(() => {
        setAffected([]);
        if (!credential) return;
        let cancelled = false;
        sendEventAsync({
            event_name: 'credential:delete',
            request_id: `delete-cred-dryrun-${Date.now()}`,
            credential_id: credential.id,
            confirm: false,
        })
            .then((response) => {
                if (!cancelled && response?.success) setAffected(response.affected_workflows ?? []);
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
            customMessage={credential ? credentialDeleteMessage(credential.name, affected) : undefined}
        />
    );
}
