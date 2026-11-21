// The check of one connected account: its provider's own answer (its channels, its repositories) or its refusal in its
// own words. Asked once when an account is first looked at and remembered for the session, so coming back to a page
// doesn't ask the provider again. Each check calls the provider and is rate-limited, so nothing sweeps a whole list.
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import type { ConnectionCheck } from '@/lib/connectionCheck';
import type { ConnectionProbe } from './Proof';

export type { ConnectionProbe };

/** Asks an account's provider about it. */
export type ProbeAsk = () => Promise<ConnectionCheck>;

const probes = new Map<string, ConnectionProbe>();
const listeners = new Set<() => void>();

function publish(accountId: string, probe: ConnectionProbe) {
    probes.set(accountId, probe);
    listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** The last check of an account this session, if it has had one. */
export function lastConnectionProbe(accountId: string): ConnectionProbe | undefined {
    return probes.get(accountId);
}

/** Checks an account now with `ask`, and keeps the answer for the session (a failed ask says nothing of the account). */
export async function runProbe(accountId: string, ask: ProbeAsk): Promise<ConnectionProbe> {
    publish(accountId, { status: 'checking' });
    let probe: ConnectionProbe;
    try {
        probe = { status: 'done', result: await ask() };
    } catch (err) {
        probe = { status: 'failed', error: err instanceof Error ? err.message : String(err) };
    }
    publish(accountId, probe);
    return probe;
}

/** The check of `accountId`, asked with `ask` the first time it's looked at; no `ask`, nothing can check it. */
export function useConnectionProbe(accountId: string, ask: ProbeAsk | undefined) {
    const state = useSyncExternalStore(
        subscribe,
        () => probes.get(accountId),
        () => undefined
    );
    const askRef = useRef(ask);
    askRef.current = ask;
    const canCheck = !!ask;
    const check = useCallback(() => {
        if (askRef.current) void runProbe(accountId, askRef.current);
    }, [accountId]);
    useEffect(() => {
        if (canCheck && !probes.has(accountId)) check();
    }, [accountId, canCheck, check]);
    return { probe: state, check, canCheck };
}
