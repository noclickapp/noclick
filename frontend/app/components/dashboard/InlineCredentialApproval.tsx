// Review credential actions inside the dashboard using the standalone page's
// authenticated loader and CSRF-protected action. Both surfaces render the same
// immutable details, so inline decisions cannot bypass the normal approval checks.
import { useEffect, useRef } from 'react';
import { useFetcher } from 'react-router';
import {
    CredentialApproval,
    type ReviewState,
} from '~/components/credential/CredentialApproval';

export function InlineCredentialApproval({
    approvalId,
    onDecided,
}: {
    approvalId: string;
    onDecided?: () => void;
}) {
    const review = useFetcher<{ state: ReviewState; csrfToken: string }>();
    const decision = useFetcher<{ saved?: boolean; error?: string }>();
    const notified = useRef(false);
    const path = `/credential/approval/${encodeURIComponent(approvalId)}`;
    const { load } = review;
    useEffect(() => {
        void load(path);
    }, [load, path]);
    useEffect(() => {
        if (
            decision.state === 'idle' &&
            decision.data?.saved &&
            !notified.current
        ) {
            notified.current = true;
            void load(path);
            onDecided?.();
        }
    }, [decision.state, decision.data, load, path, onDecided]);

    if (!review.data)
        return (
            <p role="status" className="py-5 text-sm text-muted-foreground">
                Loading action…
            </p>
        );
    return (
        <CredentialApproval
            embedded
            state={review.data.state}
            saving={decision.state !== 'idle' || !!decision.data?.saved}
            error={decision.data?.error}
            onDecide={(value) => {
                notified.current = false;
                void decision.submit(
                    {
                        csrf_token: review.data!.csrfToken,
                        payload: JSON.stringify({ decision: value }),
                    },
                    { method: 'post', action: path }
                );
            }}
        />
    );
}
