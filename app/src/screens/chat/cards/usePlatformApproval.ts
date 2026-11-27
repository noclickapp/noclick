// One approval NoClick asked for, as its card in the chat shows it: read on /v1 with the page's client (GET
// /v1/approvals/{id}, the answer the approval page's loader shows too) and, by the account's signed-in owner, answered
// as that page answers it (POST /v1/approvals/{id}/answer; a key can't, ownerOnly.ts). Read again on the account's frame
// that it moved (answered in the Beside's review, on its page, on a phone, in another tab) and when the tab comes back
// into focus while it waits.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkFrames } from '@/sdk/live';
import { useClient } from '@/sdk/client';
import { Approval, NoClickError, type NoClick } from 'noclick';
import type { ApprovalView, Failure } from '../approvals';

/** The approval as /v1 answers it to the account. */
export async function readApproval(client: NoClick, approvalId: string): Promise<ApprovalView> {
    return (await Approval.fromId(approvalId, { client }).refresh()).raw as unknown as ApprovalView;
}

/** A /v1 call's refusal as the approval page shows one: its message and what to do next. */
export function failureOfError(error: unknown): Failure {
    if (error instanceof NoClickError) return { status: error.status ?? 0, message: error.message, next_step: error.nextStep };
    return { status: 0, message: error instanceof Error ? error.message : String(error), next_step: null };
}

/** The last answer sent: the decided approval, or why not. */
type Answered = { approval: ApprovalView } | { failure: Failure };

export function usePlatformApproval(approvalId: string) {
    const client = useClient();
    const [read, setRead] = useState<ApprovalView | null>(null);
    const [unreadable, setUnreadable] = useState(false);
    const [answer, setAnswer] = useState<Answered | null>(null);
    const [answering, setAnswering] = useState(false);
    // Reads overlap (a frame, a focus): the newest one started is the one kept.
    const latest = useRef(0);
    const load = useCallback(async () => {
        // None to read: a channel's card for someone who doesn't answer it reads nothing.
        if (!approvalId) return;
        const mine = ++latest.current;
        try {
            const view = await readApproval(client, approvalId);
            if (mine !== latest.current) return;
            setRead(view);
            setUnreadable(false);
        } catch (error) {
            if (mine !== latest.current) return;
            console.warn('[coordinator] reading the approval failed:', error);
            setUnreadable(true);
        }
    }, [client, approvalId]);
    useEffect(() => {
        void load();
    }, [load]);

    useWorkFrames(
        'platform:resource',
        (frame) => {
            if (frame.kind === 'approval' && frame.id === approvalId) void load();
        }
    );

    const answered = answer && 'approval' in answer ? answer.approval : undefined;
    // A read from before the answer still says pending; the answer is newer.
    const approval = answered && (!read || read.status === 'pending') ? answered : (read ?? undefined);
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
            try {
                const held = Approval.fromId(approvalId, { client });
                const view = decision === 'approve' ? await held.approve() : await held.decline();
                setAnswer({ approval: view.raw as unknown as ApprovalView });
            } catch (error) {
                setAnswer({ failure: failureOfError(error) });
            } finally {
                setAnswering(false);
            }
        },
        [client, approvalId]
    );
    return {
        approval,
        /** It couldn't be read here (another account's, or the platform didn't answer). */
        unreadable: unreadable && !read,
        answering,
        failure: answer && 'failure' in answer ? answer.failure : undefined,
        decide: (decision: 'approve' | 'decline') => void decide(decision),
    };
}
