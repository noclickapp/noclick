// The public credential-provide page's agent OAuth sign-in. Renders the shared
// AgentOAuthConnect (same components as the authenticated agent form) with the
// unified provideLinkTransport injected, so no transport or flow logic lives here.

import { useMemo } from 'react';
import { AgentOAuthConnect } from '~/components/workflow/AgentOAuthConnect';
import { provideLinkTransport } from './provideLinkTransport';

interface AgentOAuthProvideMethodProps {
    apiBase: string;
    token: string;
    credentialType: string;
    onProvided: () => void;
    /** Told when a sign-in call finds the request can't be provided any more. */
    onRequestEnded?: () => void;
}

export function AgentOAuthProvideMethod({ apiBase, token, credentialType, onProvided, onRequestEnded }: AgentOAuthProvideMethodProps) {
    const sendEvent = useMemo(
        () => provideLinkTransport(apiBase, token, credentialType, onRequestEnded),
        [apiBase, token, credentialType, onRequestEnded],
    );

    // The provide page has no credentialIds to manage — it only cares that the
    // credential got stored (onCredentialCreated fires the page's success screen).
    return (
        <AgentOAuthConnect
            credentialType={credentialType}
            credentialIds={{}}
            onCredentialIdsChange={() => {}}
            onCredentialCreated={async () => { onProvided(); }}
            sendEvent={sendEvent}
        />
    );
}
