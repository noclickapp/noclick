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
}

export function AgentOAuthProvideMethod({ apiBase, token, credentialType, onProvided }: AgentOAuthProvideMethodProps) {
    const sendEvent = useMemo(
        () => provideLinkTransport(apiBase, token, credentialType),
        [apiBase, token, credentialType],
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
