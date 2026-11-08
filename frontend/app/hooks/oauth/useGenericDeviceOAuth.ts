import { useCallback, useEffect, useRef, useState } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';
import type { UseOAuthHookOptions } from './createOAuthHook';

export interface DeviceAuthorization {
    provider: string;
    userCode: string;
    verificationUrl: string;
    polling: boolean;
    check: () => void;
}

/** The standard device flow, on the same transport as redirect OAuth (socket or connect link). */
export function useGenericDeviceOAuth(options: UseOAuthHookOptions) {
    const exchange = useOAuthExchange();
    const latest = useRef({ exchange, options });
    latest.current = { exchange, options };
    const generation = useRef(0);
    const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const [isConnecting, setConnecting] = useState(false);
    const [authorization, setAuthorization] =
        useState<DeviceAuthorization | null>(null);
    const cancel = useCallback(() => {
        generation.current++;
        clearTimeout(timer.current);
        setConnecting(false);
        setAuthorization(null);
    }, []);
    useEffect(() => cancel, [cancel]);
    const connect = useCallback(
        async (
            provider: string,
            scopes: string[],
            context: Record<string, string>
        ) => {
            cancel();
            const current = generation.current;
            const alive = () => current === generation.current;
            setConnecting(true);
            const fail = (message: string) => {
                if (!alive()) return;
                cancel();
                latest.current.options.onError?.(message);
            };
            try {
                const started = await latest.current.exchange({
                    event_name: 'oauth:device:start',
                    provider,
                    scopes,
                    context,
                });
                if (!alive()) return;
                if (
                    !started?.success ||
                    !started.authorization_id ||
                    !started.user_code ||
                    !started.verification_uri
                )
                    throw new Error(
                        started?.message || 'Could not start device sign-in'
                    );
                const deadline = Date.now() + started.expires_in * 1000;
                let inFlight = false;
                const poll = async () => {
                    if (!alive() || inFlight) return;
                    clearTimeout(timer.current);
                    if (Date.now() >= deadline)
                        return fail(
                            'Device code expired. Start sign-in again.'
                        );
                    inFlight = true;
                    setAuthorization(
                        (value) => value && { ...value, polling: true }
                    );
                    try {
                        const response = await latest.current.exchange({
                            event_name: 'oauth:device:poll',
                            provider,
                            authorization_id: started.authorization_id,
                        });
                        if (!alive()) return;
                        if (!response?.success)
                            throw new Error(
                                response?.message || 'Device sign-in failed'
                            );
                        if (
                            response.status === 'completed' &&
                            response.credential_id
                        ) {
                            cancel();
                            latest.current.options.onSuccess?.({
                                success: true,
                                provider,
                                credentialId: response.credential_id,
                                credentialName: response.credential_name,
                                name: response.name,
                            });
                            return;
                        }
                        if (
                            response.status !== 'pending' &&
                            response.status !== 'slow_down'
                        )
                            throw new Error(
                                response.status === 'expired'
                                    ? 'Device code expired. Start sign-in again.'
                                    : 'Device sign-in was refused.'
                            );
                        timer.current = setTimeout(
                            () => void poll(),
                            Math.max(1, response.interval ?? started.interval) *
                                1000
                        );
                    } catch (error) {
                        fail(
                            error instanceof Error
                                ? error.message
                                : 'Device sign-in failed'
                        );
                    } finally {
                        inFlight = false;
                        if (alive())
                            setAuthorization(
                                (value) => value && { ...value, polling: false }
                            );
                    }
                };
                setAuthorization({
                    provider,
                    userCode: started.user_code,
                    verificationUrl: started.verification_uri,
                    polling: false,
                    check: () => void poll(),
                });
                timer.current = setTimeout(
                    () => void poll(),
                    Math.max(1, started.interval) * 1000
                );
            } catch (error) {
                fail(
                    error instanceof Error
                        ? error.message
                        : 'Device sign-in failed'
                );
            }
        },
        [cancel]
    );
    return { connect, cancel, isConnecting, authorization };
}
