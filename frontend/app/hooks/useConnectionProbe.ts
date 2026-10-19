// The credential:test_connection probe for one connected account: the
// provider's own answer (their channels, their repositories) or its verbatim
// refusal. Runs once when an account is first looked at and is remembered for
// the session, so coming back to a page doesn't ask the provider again. The
// probe calls the provider and is rate-limited, so nothing sweeps a whole list.
import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { CredentialTestConnectionRequest, sendEventAsync } from '~/lib/socket-sender';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';

export type ConnectionProbe =
    | { status: 'checking' }
    | { status: 'done'; result: CredentialTestConnectionResponse }
    /** The request itself failed (rate limit, socket): says nothing about the account. */
    | { status: 'failed'; error: string };

const probes = new Map<string, ConnectionProbe>();
const listeners = new Set<() => void>();

function publish(credentialId: string, probe: ConnectionProbe) {
    probes.set(credentialId, probe);
    listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** The last probe of an account this session, if it has had one. */
export function lastConnectionProbe(credentialId: string): ConnectionProbe | undefined {
    return probes.get(credentialId);
}

async function probe(credentialId: string, nodeType: string) {
    publish(credentialId, { status: 'checking' });
    try {
        const response = (await sendEventAsync(CredentialTestConnectionRequest.create({ node_type: nodeType, credential_id: credentialId }))) as
            | (CredentialTestConnectionResponse & { error?: string | null })
            | null;
        if (!response || (response.reachable === undefined && response.error)) {
            publish(credentialId, { status: 'failed', error: response?.error || 'No answer' });
            return;
        }
        publish(credentialId, { status: 'done', result: response });
    } catch (err) {
        publish(credentialId, { status: 'failed', error: err instanceof Error ? err.message : String(err) });
    }
}

/** Probe once, as a connect flow does right after a sign-in lands, and hand back the provider's answer (null when the
 *  request itself failed, which says nothing about the account). */
export async function probeConnection(credentialId: string, nodeType: string): Promise<CredentialTestConnectionResponse | null> {
    await probe(credentialId, nodeType);
    const result = probes.get(credentialId);
    return result?.status === 'done' ? result.result : null;
}

/** Probe `credentialId` through `nodeType`'s evidence declaration; `undefined` node type = nothing can be asked. */
export function useConnectionProbe(credentialId: string, nodeType: string | undefined) {
    const state = useSyncExternalStore(
        subscribe,
        () => probes.get(credentialId),
        () => undefined
    );
    useEffect(() => {
        if (nodeType && !probes.has(credentialId)) void probe(credentialId, nodeType);
    }, [credentialId, nodeType]);
    const check = useCallback(() => {
        if (nodeType) void probe(credentialId, nodeType);
    }, [credentialId, nodeType]);
    return { probe: state, check, canCheck: !!nodeType };
}
