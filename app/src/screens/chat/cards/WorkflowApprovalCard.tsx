// A workflow's Approval step waiting on the account's owner, drawn under NoClick's note about it in the chat: the step's
// title, its workflow and the values it asks about, with Approve and Decline, answered as the owner's one-tap link and
// their code answer it (`useWorkflowApproval`). Only the account's signed-in owner answers it here. Answered, expired or
// answered elsewhere, it reads back as one line.
import { ShieldCheck } from 'lucide-react';
import { GlyphTile, InlineCard, PILL_PRIMARY, PILL_QUIET, Receipt, Status } from '@/ui/chat/primitives';
import { useOwnerOnly } from '@/screens/console/ownerOnly';
import type { WorkflowApprovalNote } from '@/lib/agentThread/thread';
import { useWorkflowApproval } from './useWorkflowApproval';

/** Who answered it, as the receipt says it. */
const BY: Record<string, string> = { owner: 'You', code: 'Your code', app: 'Someone in the NoClick app' };

/** The values it asks about, by their fields' labels, in the fields' order. */
function rows(values: Record<string, unknown>, fields: readonly { name: string; label: string }[]): [string, string][] {
    const named = fields.filter((f) => f.name in values).map((f): [string, string] => [f.label || f.name, String(values[f.name] ?? '')]);
    return named.length ? named : Object.entries(values).map(([k, v]): [string, string] => [k, String(v ?? '')]);
}

export function WorkflowApprovalCard({ note }: { note: WorkflowApprovalNote }) {
    const review = useWorkflowApproval(note.workflowId, note.id);
    const answers = useOwnerOnly()('approvals');
    const live = review.approval;
    const what = live?.title || note.title || 'its approval';
    const workflow = live?.workflowName || note.workflowName;
    const lapsed = live?.status === 'pending' && !!live.expiresAt && live.expiresAt.getTime() <= Date.now();
    const status = lapsed ? 'expired' : live?.status;

    if (status === 'approved' || status === 'declined') {
        const who = BY[live?.decidedBy ?? ''] ?? 'Someone';
        return (
            <Receipt tone={status === 'approved' ? 'done' : 'info'}>
                {who} {status} · {what} ({workflow})
            </Receipt>
        );
    }
    if (status === 'expired') return <Receipt tone="info">Nobody answered in time, so the run ended · {what}</Receipt>;
    if (review.unreadable) return <Receipt tone="info">Waiting for approval · {what}</Receipt>;

    const ready = !!live && !review.answering && answers;
    const shown = live ? rows(live.values, live.fields) : [];
    return (
        <div data-testid="workflow-approval">
            <InlineCard
                lead={
                    <GlyphTile>
                        <ShieldCheck className="h-4 w-4" />
                    </GlyphTile>
                }
                title={what}
                meta={`${workflow} · ${answers ? 'waiting for your OK' : 'waiting for the owner'}`}
                actions={
                    answers ? (
                        <>
                            <button type="button" className={PILL_PRIMARY} disabled={!ready} onClick={() => review.decide('approve')}>
                                Approve
                            </button>
                            <button type="button" className={PILL_QUIET} disabled={!ready} onClick={() => review.decide('decline')}>
                                Decline
                            </button>
                        </>
                    ) : undefined
                }
            >
                {!live && <Status state="working">Checking it’s still waiting</Status>}
                {shown.length > 0 && (
                    <dl className="space-y-1 text-[13px]" data-testid="workflow-approval-values">
                        {shown.map(([label, value]) => (
                            <div key={label} className="flex gap-3">
                                <dt className="w-1/3 shrink-0 text-muted-foreground">{label}</dt>
                                <dd className="min-w-0 whitespace-pre-wrap break-words text-foreground">{value}</dd>
                            </div>
                        ))}
                    </dl>
                )}
                {review.failure && (
                    <p className="text-[13px] text-red-600 dark:text-red-400">
                        {review.failure.message}
                        {review.failure.next_step ? ` ${review.failure.next_step}` : ''}
                    </p>
                )}
            </InlineCard>
        </div>
    );
}
