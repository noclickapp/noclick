// Connecting an integration through its vendor's own MCP server (backend nodes/oauth/mcp_connect.py). The backend
// runs the MCP auth spec and answers where to sign in; this opens that in a window, hears the code come back to
// /api/auth/mcp/callback (on its BroadcastChannel, else postMessage, matched by state), and finishes. A server that
// takes a bearer key instead asks for it (`needsKey`). One engine for every surface: the in-app socket by default, a
// provide link's HTTP transport where one is passed (provideLinkTransport maps the same two events).
import { useCallback, useEffect, useRef, useState } from 'react';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { MCP_CALLBACK_PATH, MCP_CALLBACK_TYPE } from '~/lib/mcpCallback';
import { oauthChannelName } from '~/lib/oauthChannel';
import { openTabForLater } from '~/lib/oauthPopup';
import { sendEventAsync } from '~/lib/socket-sender';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';

export interface McpConnectedCredential {
    id: string;
    name: string;
    credential_type: string;
}

export type McpConnectStage =
    | 'idle'
    | 'starting'
    | 'signing_in'
    | 'key'
    | 'finishing';

interface McpCallback {
    type?: string;
    success?: boolean;
    code?: string;
    state?: string;
    error?: string;
    error_description?: string;
}

interface Started {
    success?: boolean;
    kind?: 'oauth' | 'key' | 'none';
    flow?: string;
    authorization_url?: string;
    state?: string;
    error?: string;
}

interface Finished {
    success?: boolean;
    credential?: McpConnectedCredential;
    verification?: CredentialTestConnectionResponse | null;
    error?: string;
}

const failure = (err: unknown) => ({
    success: false,
    error: err instanceof Error ? err.message : String(err),
});

export function useMcpConnect({
    credentialType,
    sendEvent = sendEventAsync,
    onConnected,
}: {
    credentialType: string;
    sendEvent?: OAuthExchange;
    onConnected: (
        credential: McpConnectedCredential,
        verification: CredentialTestConnectionResponse | null
    ) => void;
}) {
    const [stage, setStage] = useState<McpConnectStage>('idle');
    const [error, setError] = useState<string | null>(null);
    const flowRef = useRef<{
        flow: string;
        state?: string;
        kind: string;
    } | null>(null);
    const stopListening = useRef<() => void>(() => undefined);
    const onConnectedRef = useRef(onConnected);
    onConnectedRef.current = onConnected;

    useEffect(() => () => stopListening.current(), []);

    const finish = useCallback(
        async (fields: { code?: string; state?: string; api_key?: string }) => {
            const started = flowRef.current;
            if (!started) return;
            setStage('finishing');
            const answer = (await sendEvent({
                event_name: 'mcp:connect:finish',
                credential_type: credentialType,
                flow: started.flow,
                ...fields,
            }).catch(failure)) as Finished;
            if (answer?.success && answer.credential) {
                flowRef.current = null;
                setStage('idle');
                onConnectedRef.current(
                    answer.credential,
                    answer.verification ?? null
                );
                return;
            }
            setError(answer?.error || 'The connection could not be finished.');
            setStage(started.kind === 'key' ? 'key' : 'idle');
            if (started.kind !== 'key') flowRef.current = null;
        },
        [credentialType, sendEvent]
    );

    const listen = useCallback(
        (state: string) => {
            stopListening.current();
            const heard = (data: McpCallback) => {
                if (data?.type !== MCP_CALLBACK_TYPE || data.state !== state)
                    return;
                stopListening.current();
                if (!data.success || !data.code) {
                    setError(
                        data.error_description ||
                            data.error ||
                            'The sign-in did not finish.'
                    );
                    setStage('idle');
                    flowRef.current = null;
                    return;
                }
                void finish({ code: data.code, state });
            };
            const onMessage = (event: MessageEvent) => {
                if (event.origin === window.location.origin)
                    heard(event.data as McpCallback);
            };
            window.addEventListener('message', onMessage);
            let channel: BroadcastChannel | null = null;
            try {
                // A sign-in page that severs the opener (COOP) still reaches the channel.
                channel = new BroadcastChannel(oauthChannelName('mcp', state));
                channel.onmessage = (event) => heard(event.data as McpCallback);
            } catch {
                channel = null;
            }
            stopListening.current = () => {
                window.removeEventListener('message', onMessage);
                channel?.close();
                stopListening.current = () => undefined;
            };
        },
        [finish]
    );

    const connect = useCallback(async () => {
        setError(null);
        setStage('starting');
        // Opened while the click still counts, so no popup blocker stops it; pointed at the sign-in once it's known.
        const signIn = openTabForLater({ name: `mcp-connect-${credentialType}`, popup: { width: 520, height: 720 } });
        const popup = signIn.window;
        const started = (await sendEvent({
            event_name: 'mcp:connect:start',
            credential_type: credentialType,
            redirect_uri: `${window.location.origin}${MCP_CALLBACK_PATH}`,
        }).catch(failure)) as Started;
        if (!started?.success || !started.flow) {
            signIn.close();
            setError(started?.error || 'The connection could not start.');
            setStage('idle');
            return;
        }
        flowRef.current = {
            flow: started.flow!,
            state: started.state,
            kind: started.kind ?? 'oauth',
        };
        if (started.kind === 'key') {
            signIn.close();
            setStage('key');
            return;
        }
        if (started.kind === 'none') {
            signIn.close();
            await finish({});
            return;
        }
        if (!popup) {
            setError(
                'Your browser blocked the sign-in window. Allow pop-ups for this site and try again.'
            );
            setStage('idle');
            return;
        }
        listen(started.state!);
        setStage('signing_in');
        signIn.go(started.authorization_url!);
    }, [credentialType, sendEvent, finish, listen]);

    const submitKey = useCallback(
        (key: string) => finish({ api_key: key }),
        [finish]
    );

    const cancel = useCallback(() => {
        stopListening.current();
        flowRef.current = null;
        setStage('idle');
    }, []);

    return {
        stage,
        error,
        clearError: () => setError(null),
        connect,
        submitKey,
        cancel,
    };
}
