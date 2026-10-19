// Review credential actions inside the dashboard using the standalone page's
// authenticated loader and CSRF-protected action. Both surfaces render the same
// immutable details, so inline decisions cannot bypass the normal approval checks.
import { CredentialApproval } from '~/components/credential/CredentialApproval';
import { useCredentialApprovalReview } from '~/hooks/useCredentialApprovalReview';

export function InlineCredentialApproval({
    approvalId,
    onDecided,
}: {
    approvalId: string;
    onDecided?: () => void;
}) {
    const review = useCredentialApprovalReview(approvalId, onDecided);
    if (!review.state)
        return (
            <p role="status" className="py-5 text-sm text-muted-foreground">
                Loading action…
            </p>
        );
    return (
        <CredentialApproval
            embedded
            state={review.state}
            saving={review.saving}
            error={review.error}
            onDecide={(value) => review.decide(value as 'approved' | 'rejected')}
        />
    );
}
