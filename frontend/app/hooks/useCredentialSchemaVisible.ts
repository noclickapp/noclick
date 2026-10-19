// Whether a credential class is offered to this viewer. A class can be `x-credential-hidden` (pending marketplace
// approval, e.g. Meta OAuth) yet carry `x-credential-preview-flag`: a PostHog flag that reveals it for allow-listed
// accounts (Meta reviewers) so the live connect flow can be demoed before Advanced Access. Revealed for our own dev
// servers (no PostHog; `make local` runs a dev server too, so self-hosted stays hidden), internal users (opted out of
// PostHog, so the flag never loads for them), or accounts the flag targets.
import { useCallback } from 'react';
import { useActiveFeatureFlags } from 'posthog-js/react';
import { useSnapshot } from 'valtio';
import { isLocalEdition } from '~/lib/edition';
import { featureGateState } from '~/lib/featureGates';
import { isInternalEmail } from '~/lib/internalUsers';

export function useCredentialSchemaVisible(): (credentialSchema: Record<string, unknown> | undefined) => boolean {
    const activeFeatureFlags = useActiveFeatureFlags();
    const { email } = useSnapshot(featureGateState);
    const internalUser = !!email && isInternalEmail(email);
    return useCallback(
        (credentialSchema) => {
            if (!credentialSchema?.['x-credential-hidden']) return true;
            const previewFlag = credentialSchema['x-credential-preview-flag'];
            if (typeof previewFlag !== 'string') return false;
            return (import.meta.env.DEV && !isLocalEdition()) || internalUser || !!activeFeatureFlags?.includes(previewFlag);
        },
        [activeFeatureFlags, internalUser]
    );
}
