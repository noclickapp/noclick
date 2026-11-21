// The one confirmation for deleting a connected account: it asks what still uses it (the automations, and whatever else
// holds it: an agent, an app, an MCP server), names them, then deletes it. Where the account came from says how
// (`through`: its connection on the platform API, or a host's own way).
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { DeleteConfirmPopup } from '@/ui/DeleteConfirmPopup';

export interface DeletableAccount {
    id: string;
    name: string;
}

/** An automation that loses the account. */
export interface AffectedWorkflow {
    workflow_id: string;
    workflow_name: string;
}

/** Something else that holds the account (an agent, an app, an MCP server), and what uses that. */
export interface AffectedHolder {
    kind: string;
    id: string;
    name: string;
    used_by?: string[] | null;
}

export interface Affected {
    workflows: AffectedWorkflow[];
    holders: AffectedHolder[];
}

/** How what deleting it leaves without it is found, and how it's deleted. */
export interface DeletesThrough {
    preview: () => Promise<Affected>;
    remove: () => Promise<void>;
}

const NOTHING: Affected = { workflows: [], holders: [] };

function holderLabel(holder: AffectedHolder): string {
    const usedBy = holder.used_by?.length ? ` (used by ${holder.used_by.join(', ')})` : '';
    return `the ${holder.kind} "${holder.name}"${usedBy}`;
}

/** The warning the dialog shows once it knows what depends on the account. */
export function credentialDeleteMessage(name: string, affected: AffectedWorkflow[], holders: AffectedHolder[]): string | undefined {
    const lines: string[] = [];
    if (affected.length) {
        const names = affected
            .slice(0, 5)
            .map((w) => w.workflow_name)
            .join(', ');
        lines.push(
            `"${name}" is used by ${affected.length} workflow${affected.length === 1 ? '' : 's'}: ${names}${affected.length > 5 ? ', …' : ''}. Deleting it will deactivate their triggers and break those nodes until you connect a new credential.`
        );
    }
    if (holders.length) {
        const labels = holders.map(holderLabel);
        const listed = labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
        lines.push(`Deleting "${name}" also disconnects ${listed} until it's reconnected.`);
    }
    return lines.length ? lines.join(' ') : undefined;
}

/** Open while `account` is set. `removing` says it as removing it (its access ends everywhere), where a page's button
 *  says Remove; `onDeleted` runs once it's gone. */
export function ConnectionDeleteDialog({
    account,
    through,
    onClose,
    onDeleted,
    removing,
}: {
    account: DeletableAccount | null;
    through: DeletesThrough;
    onClose: () => void;
    onDeleted?: () => void;
    removing?: boolean;
}) {
    const [affected, setAffected] = useState<Affected>(NOTHING);
    const throughRef = useRef(through);
    throughRef.current = through;

    // While the dialog is open: what still holds the account, without deleting anything.
    useEffect(() => {
        setAffected(NOTHING);
        if (!account) return;
        let cancelled = false;
        throughRef.current
            .preview()
            .then((found) => {
                if (!cancelled) setAffected(found);
            })
            .catch(() => {
                // Non-fatal: the dialog shows the generic warning instead.
            });
        return () => {
            cancelled = true;
        };
    }, [account]);

    const confirm = useCallback(async () => {
        if (!account) return;
        try {
            await throughRef.current.remove();
            toast.success('Credential deleted');
            onDeleted?.();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to delete credential');
        } finally {
            onClose();
        }
    }, [account, onClose, onDeleted]);

    return (
        <DeleteConfirmPopup
            itemType="Credential"
            itemName={account?.name}
            title={removing && account ? `Remove ${account.name}?` : undefined}
            confirmLabel={removing ? 'Remove' : undefined}
            isOpen={!!account}
            onOpenChange={(open) => {
                if (!open) onClose();
            }}
            onConfirmDelete={confirm}
            customMessage={account ? credentialDeleteMessage(account.name, affected.workflows, affected.holders) : undefined}
        />
    );
}
