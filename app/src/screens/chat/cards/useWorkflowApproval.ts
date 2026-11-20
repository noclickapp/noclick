// A workflow's Approval step that waits on the account's owner, as its card in the chat shows it: read on /v1 with the
// page's client (GET /v1/workflows/{id}/approvals/{approval_id}) and answered there (POST .../answer), the same path the
// owner's one-tap link and their code answer it through. Read again when the tab comes back into focus while it waits:
// it may have been answered from a text, the link or code meanwhile.
import { useCallback, useEffect, useRef, useState } from 'react';
import { WorkflowApproval } from 'noclick';
import { useClient } from '@/sdk/client';
import type { Failure } from '../approvals';
import { failureOfError } from './usePlatformApproval';

/** What the card reads of the step. */
export interface WorkflowApprovalState {
    status: WorkflowApproval['status'];
    title: string | null;
    workflowName: string | null;
    values: Record<string, unknown>;
    fields: WorkflowApproval['fields'];
    decidedBy: WorkflowApproval['decidedBy'];
    expiresAt: Date | null;
}

const stateOf = (approval: WorkflowApproval): WorkflowApprovalState => ({
    status: approval.status,
    title: approval.title,
    workflowName: approval.workflowName,
    values: approval.values,
    fields: approval.fields,
    decidedBy: approval.decidedBy,
    expiresAt: approval.expiresAt,
});

export function useWorkflowApproval(workflowId: string, approvalId: string) {
    const client = useClient();
    const [approval, setApproval] = useState<WorkflowApprovalState | null>(null);
    const [unreadable, setUnreadable] = useState(false);
    const [answering, setAnswering] = useState(false);
    const [failure, setFailure] = useState<Failure | null>(null);
    // Reads overlap (a focus, an answer): the newest one started is the one kept.
    const latest = useRef(0);

    const load = useCallback(async () => {
        const mine = ++latest.current;
        try {
            const read = await WorkflowApproval.fromId(workflowId, approvalId, { client }).hydrate();
            if (mine !== latest.current) return;
            setApproval(stateOf(read));
            setUnreadable(false);
        } catch (error) {
            if (mine !== latest.current) return;
            console.warn('[chat] reading the workflow approval failed:', error);
            setUnreadable(true);
        }
    }, [client, workflowId, approvalId]);

    useEffect(() => {
        void load();
    }, [load]);

    const waiting = !approval || approval.status === 'pending';
    useEffect(() => {
        if (!waiting) return;
        const look = () => void load();
        window.addEventListener('focus', look);
        return () => window.removeEventListener('focus', look);
    }, [waiting, load]);

    const decide = useCallback(
        async (decision: 'approve' | 'decline') => {
            setAnswering(true);
            setFailure(null);
            ++latest.current;
            try {
                const step = WorkflowApproval.fromId(workflowId, approvalId, { client });
                setApproval(stateOf(await (decision === 'approve' ? step.approve() : step.decline())));
            } catch (error) {
                setFailure(failureOfError(error));
                void load();
            } finally {
                setAnswering(false);
            }
        },
        [client, workflowId, approvalId, load]
    );

    return {
        approval,
        /** It couldn't be read here (another account's, or the platform didn't answer). */
        unreadable: unreadable && !approval,
        answering,
        failure,
        decide: (decision: 'approve' | 'decline') => void decide(decision),
    };
}
