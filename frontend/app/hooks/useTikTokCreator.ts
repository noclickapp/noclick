// Load creator capabilities through the existing credential-gated options event.
// Ignore stale responses when the selected account changes.
import { useEffect, useState } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowNodeLoadOptionsRequest } from '~/types/socket-events.generated';
import type {
    FieldOption,
    WorkflowNodeLoadOptionsResponse,
} from '~/types/socket-events.generated';

export function useTikTokCreator(credentialId: string, refresh: number) {
    const [state, setState] = useState<{
        credentialId: string;
        loading: boolean;
        options: FieldOption[];
        error?: string;
    }>({ credentialId: '', loading: false, options: [] });
    useEffect(() => {
        let current = true;
        setState({ credentialId, loading: Boolean(credentialId), options: [] });
        if (credentialId) {
            void sendEventAsync(
                WorkflowNodeLoadOptionsRequest.create({
                    request_id: `tiktok-creator-${crypto.randomUUID()}`,
                    node_type: 'automation-tiktok',
                    field_name: 'privacy_level',
                    credential_id: credentialId,
                })
            )
                .then((raw) => {
                    if (!current) return;
                    const response = raw as WorkflowNodeLoadOptionsResponse;
                    setState({
                        credentialId,
                        loading: false,
                        options: response.success
                            ? (response.options ?? [])
                            : [],
                        error: response.success
                            ? undefined
                            : response.message ||
                              'Could not load TikTok creator options.',
                    });
                })
                .catch(() => {
                    if (current)
                        setState({
                            credentialId,
                            loading: false,
                            options: [],
                            error: 'Could not load TikTok creator options. Try refreshing.',
                        });
                });
        }
        return () => {
            current = false;
        };
    }, [credentialId, refresh]);
    return state.credentialId === credentialId
        ? state
        : { credentialId, loading: Boolean(credentialId), options: [] };
}
