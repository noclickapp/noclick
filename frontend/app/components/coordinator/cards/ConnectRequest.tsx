// The way in for an account the coordinator asked to connect, run on the coordinator's own credential request: its
// methods drawn by the provide page's connect UI over the request's token, so a key is judged by the same connect
// seam, a sign-in is exchanged through the request, and the fulfilled request wakes the coordinator exactly as the
// link does. Loaded on demand: it carries every provider's sign-in.
import { useEffect, type ReactNode } from 'react';
import { CredentialMethodConnect } from '~/components/credential/CredentialMethodConnect';
import { signsInOnlyInApp, useCredentialRequest } from '~/components/credential/CredentialProvideFlow';
import { ConnectAccountCard, ConnectElsewhere, ConnectUnavailable } from '~/components/coordinator/inline/setup';
import { isLocalEdition } from '~/lib/edition';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { navigateToSettings, navigateToTab } from '~/lib/navigation';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

// Where accounts are connected: the shell's Connections page, or Settings → Credentials in the open edition's tabs.
const CONNECTIONS = isLocalEdition()
    ? { place: 'Settings → Credentials', open: () => navigateToSettings({ section: 'credentials' }) }
    : { place: 'Connections', open: () => navigateToTab('connections') };

export interface ConnectRequestProps {
    token: string;
    /** The credential type the coordinator asked for. */
    requested: string;
    name: string;
    mark: ReactNode;
    meta?: ReactNode;
    onProvided: (verification?: CredentialTestConnectionResponse | null) => void;
    /** The request was already fulfilled (here before a reload, through another way in, or by a re-scan that
     *  repaired an existing account): the credential it made. */
    onFulfilled: (credentialId?: string) => void;
    /** Read the request again: after a failed read, or when a save finds it gone, ended or out of tries. */
    onRetry: () => void;
    /** Where its plan sign-ins are offered instead (`ConnectAccountCard`). */
    onPlan?: () => void;
}

export default function ConnectRequest({ token, requested, name, mark, meta, onProvided, onFulfilled, onRetry, onPlan }: ConnectRequestProps) {
    const apiBase = apiBaseUrl();
    const request = useCredentialRequest(token, apiBase);
    const serviceName = getProviderConfigByCredentialType(requested)?.name ?? name;
    const fulfilled = request.status === 'unavailable' && request.problem === 'fulfilled';
    const credentialId = request.status === 'unavailable' ? request.credentialId : undefined;
    useEffect(() => {
        if (fulfilled) onFulfilled(credentialId);
    }, [fulfilled, credentialId, onFulfilled]);
    if (fulfilled) return null;
    if (request.status === 'unavailable') return <ConnectUnavailable name={name} problem={request.problem} onRetry={onRetry} />;
    return (
        <ConnectAccountCard
            mark={mark}
            name={name}
            meta={meta}
            requested={requested}
            methods={request.status === 'ready' ? request.methods : undefined}
            onPlan={onPlan}
            renderMethod={(method) =>
                signsInOnlyInApp(method) ? (
                    <ConnectElsewhere name={name} place={CONNECTIONS.place} onOpen={CONNECTIONS.open} />
                ) : (
                    <CredentialMethodConnect
                        method={method}
                        apiBase={apiBase}
                        token={token}
                        serviceName={serviceName}
                        // A key reads as its steps here too: get it (and where), then paste it.
                        steps
                        onProvided={onProvided}
                        onRequestEnded={onRetry}
                    />
                )
            }
        />
    );
}
