// Each connection owns its approval rules, shared by all agents and MCP clients.
// This authenticated page is also the review link sent by the coordinator;
// removing a rule is possible here only through an explicit human save.
import {
    useFetcher,
    useLoaderData,
    type ActionFunctionArgs,
    type LoaderFunctionArgs,
} from 'react-router';
import {
    CredentialPermissions,
    type CredentialPolicyState,
} from '~/components/credential/CredentialPermissions';
import {
    loadCredentialReview,
    submitCredentialReview,
} from '~/lib/credentialReview.server';

export const loader = ({ request, params }: LoaderFunctionArgs) =>
    loadCredentialReview(
        request,
        `permissions/${encodeURIComponent(params.credentialId!)}`
    );
export const action = ({ request, params }: ActionFunctionArgs) =>
    submitCredentialReview(
        request,
        `permissions/${encodeURIComponent(params.credentialId!)}`
    );

export default function CredentialPermissionsPage() {
    const { state, csrfToken } = useLoaderData() as {
        state: CredentialPolicyState;
        csrfToken: string;
    };
    const fetcher = useFetcher<{ saved?: boolean; error?: string }>();
    return (
        <CredentialPermissions
            state={state}
            saving={fetcher.state !== 'idle'}
            error={fetcher.data?.error}
            onSave={(operations) =>
                fetcher.submit(
                    {
                        csrf_token: csrfToken,
                        payload: JSON.stringify({
                            operations,
                            expected_revision: state.revision,
                        }),
                    },
                    { method: 'post' }
                )
            }
        />
    );
}
