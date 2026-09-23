// Exact-call approval links open a full review page owned by the signed-in user.
// Arguments are read-only: approval cannot silently become a different action,
// and approving once does not remove the credential's ongoing restrictions.
import {
    useFetcher,
    useLoaderData,
    type ActionFunctionArgs,
    type LoaderFunctionArgs,
} from 'react-router';
import {
    CredentialApproval,
    type ReviewState,
} from '~/components/credential/CredentialApproval';
import {
    loadCredentialReview,
    submitCredentialReview,
} from '~/lib/credentialReview.server';

export const loader = ({ request, params }: LoaderFunctionArgs) =>
    loadCredentialReview(
        request,
        `approval/${encodeURIComponent(params.approvalId!)}`
    );
export const action = ({ request, params }: ActionFunctionArgs) =>
    submitCredentialReview(
        request,
        `approval/${encodeURIComponent(params.approvalId!)}`
    );

export default function CredentialApprovalPage() {
    const { state, csrfToken } = useLoaderData() as {
        state: ReviewState;
        csrfToken: string;
    };
    const fetcher = useFetcher<{ error?: string }>();
    const decide = (decision: string) =>
        fetcher.submit(
            { csrf_token: csrfToken, payload: JSON.stringify({ decision }) },
            { method: 'post' }
        );
    return (
        <CredentialApproval
            state={state}
            saving={fetcher.state !== 'idle'}
            error={fetcher.data?.error}
            onDecide={decide}
        />
    );
}
