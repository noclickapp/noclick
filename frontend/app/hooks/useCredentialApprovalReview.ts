// One held credential call under review: the immutable details from the review page's authenticated loader, and the
// decision posted to its CSRF-protected action, so every surface that reviews one (the standalone page's inline
// variant on Needs you, the coordinator's chat) goes through the same checks.
import { useEffect, useRef } from 'react';
import { useFetcher } from 'react-router';
import type { ReviewState } from '~/components/credential/CredentialApproval';

export function useCredentialApprovalReview(approvalId: string, onDecided?: () => void) {
    const review = useFetcher<{ state: ReviewState; csrfToken: string }>();
    const decision = useFetcher<{ saved?: boolean; error?: string }>();
    const notified = useRef(false);
    const path = `/credential/approval/${encodeURIComponent(approvalId)}`;
    const { load } = review;
    useEffect(() => {
        void load(path);
    }, [load, path]);
    useEffect(() => {
        if (decision.state === 'idle' && decision.data?.saved && !notified.current) {
            notified.current = true;
            void load(path);
            onDecided?.();
        }
    }, [decision.state, decision.data, load, path, onDecided]);
    return {
        state: review.data?.state,
        saving: decision.state !== 'idle' || !!decision.data?.saved,
        error: decision.data?.error,
        decide: (value: 'approved' | 'rejected') => {
            if (!review.data) return;
            notified.current = false;
            void decision.submit({ csrf_token: review.data.csrfToken, payload: JSON.stringify({ decision: value }) }, { method: 'post', action: path });
        },
    };
}
