// What answering an attention item does, shared by every surface that lists
// them (the open edition's Activity page, the shell's Needs you page):
// approvals, builder answers and proposals go to their sockets, credential and
// trigger fixes open where they're fixed. Each answer hides the item at once and
// re-reads the queue, so the next fetch decides what's left.
import { useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import type { DashboardActions } from '~/components/dashboard/primitives';
import type { AttentionItem } from '~/components/dashboard/types';
import { dismissAttention } from '~/hooks/useDashboardOverview';
import { socketCall as call } from '~/lib/socketCall';
import { goToWorkflowNode, navigateToWorkflow } from '~/lib/navigation';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';

export type AttentionActions = Pick<
    DashboardActions,
    | 'openWorkflow'
    | 'fixTrigger'
    | 'respondApproval'
    | 'credentialApprovalDecided'
    | 'shareAsk'
    | 'decideProposal'
    | 'copyLink'
    | 'openLink'
    | 'cancelCredentialRequest'
    | 'reconnectCredential'
> & {
    /** Each resolves whether the builder took it, so a surface showing the question can step aside meanwhile. */
    answerAsk: (item: AttentionItem, answers: Record<string, unknown>) => Promise<boolean>;
    dismissAsk: (item: AttentionItem) => Promise<boolean>;
};

export function useAttentionActions(refresh: () => Promise<void>): AttentionActions {
    const failing = useCallback(
        (what: string) => (e: unknown) => {
            toast.error(`${what} failed: ${e instanceof Error ? e.message : String(e)}`);
            void refresh();
        },
        [refresh]
    );
    const answer = useCallback(
        (item: AttentionItem, values: Record<string, unknown>, dismissed: boolean) => {
            dismissAttention(item.id);
            return call('workflow:builder:input_response', { conversation_id: item.meta?.conversationId, ask_id: item.meta?.askId, values, dismissed })
                .then(refresh)
                .then(
                    () => true,
                    (e: unknown) => {
                        failing(dismissed ? 'Skip' : 'Answer')(e);
                        return false;
                    }
                );
        },
        [refresh, failing]
    );

    return useMemo<AttentionActions>(
        () => ({
            openWorkflow: (wf, nodeId) => (nodeId ? goToWorkflowNode(wf.id, nodeId) : navigateToWorkflow({ id: wf.id, name: wf.name })),
            fixTrigger: (item) => {
                if (!item.workflow) return;
                // The same load_value field the trigger panel's Status button
                // runs (Slack join_channel): it performs the fix, re-registers
                // and stamps the verdict, so the refetch decides the item.
                const meta = item.meta ?? {};
                const action = meta.action as { field: string; label: string };
                call('workflow:node:load_value', {
                    node_type: meta.nodeType,
                    field_name: action.field,
                    workflow_id: item.workflow.id,
                    node_id: meta.nodeId,
                    context: meta.context,
                    credential_ids: meta.credentialIds,
                })
                    .then((res) => {
                        const r = res as { success?: boolean; message?: string; values?: Record<string, unknown> };
                        if (r.success === false) throw new Error(r.message || 'failed');
                        const status = String(r.values?.subscription_status ?? '');
                        if (status.startsWith('⚠')) throw new Error(status.replace(/^⚠\s*/, ''));
                        toast.success(status || 'Done');
                    })
                    .then(refresh)
                    .catch(failing(action.label));
            },
            respondApproval: (item, decision, values) => {
                dismissAttention(item.id);
                call('approval:respond', { approval_id: item.meta?.approvalId, decision, values }).then(refresh).catch(failing('Approval'));
            },
            credentialApprovalDecided: (item) => {
                dismissAttention(item.id);
                toast.success('Decision saved');
                void refresh();
            },
            answerAsk: (item, answers) => answer(item, answers, false),
            dismissAsk: (item) => answer(item, {}, true),
            shareAsk: async (item) => {
                try {
                    const d = await call('workflow:builder:share_ask', { conversation_id: item.meta?.conversationId, ask_id: item.meta?.askId });
                    const url = typeof d.url === 'string' ? d.url : typeof d.link_url === 'string' ? d.link_url : null;
                    if (!url) throw new Error('No link returned');
                    return url;
                } catch (e) {
                    toast.error(`Could not mint a link: ${e instanceof Error ? e.message : String(e)}`);
                    return null;
                }
            },
            decideProposal: (item, decision) => {
                if (!item.workflow) return;
                dismissAttention(item.id);
                call('agent:builder_decision', {
                    workflow_id: item.workflow.id,
                    node_id: item.meta?.nodeId ?? null,
                    conversation_id: item.meta?.conversationId,
                    proposal_id: item.meta?.proposalId,
                    decision,
                })
                    .then(refresh)
                    .catch(failing('Decision'));
                if (decision === 'approved') {
                    // Same hand-off as the chat card: open the workflow, expand the
                    // builder, and submit the agent-anchored prompt.
                    navigateToWorkflow({ id: item.workflow.id, name: item.workflow.name });
                    const prompt = String(item.meta?.anchoredPrompt ?? item.title);
                    setTimeout(() => {
                        document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
                        document.dispatchEvent(new CustomEvent('noclick:builder:submit', { detail: { prompt } }));
                    }, 400);
                }
            },
            copyLink: (item) => {
                const url = item.link ? new URL(item.link, window.location.origin).toString() : '';
                if (!url) return;
                navigator.clipboard?.writeText(url).then(() => toast.success('Link copied')).catch(() => toast.error('Could not copy'));
            },
            openLink: (item) => {
                if (item.link) window.open(new URL(item.link, window.location.origin).toString(), '_blank', 'noopener');
            },
            cancelCredentialRequest: (item) => {
                dismissAttention(item.id);
                call('credential:request:cancel', { credential_request_id: item.meta?.requestId }).then(refresh).catch(failing('Cancel'));
            },
            reconnectCredential: ({ credentialId, credentialType }) => openCreateCredential({ credentialType, credentialId, reconnect: true }),
        }),
        [refresh, failing, answer]
    );
}
