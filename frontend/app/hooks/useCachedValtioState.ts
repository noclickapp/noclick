// Hook for using cached valtio state that optionally syncs with backend via YJS/Redis.
//
// State flows one direction: setter/subscription → ref (synchronous) → React state → render.
// The ref is the synchronous source of truth for rapid chaining (e.g., streaming text chunks).
// React state is updated via functional updates to avoid clobbering from Valtio subscriptions.
//
// Persistence: sessionStorage (tab-specific) + IndexedDB (cross-tab), written synchronously in setter.
// YJS/Redis sync: rate-limited proxy writes (100ms debounce). Set skipRedisSync=true to skip.

import { subscribe } from 'valtio';
import { useCallback, useState, useEffect, useRef } from 'react';
import { getCachedComponentValtio, getLocalComponentValtio } from '~/state';
import { subscribeKey } from 'valtio/utils';
import { valtioCache } from '~/lib/indexeddb';
import { valtioSessionCache } from '~/lib/session-cache';

export function useCachedValtioState<T = any>(
    valtio_path: string,
    key: string,
    initialValue: T,
    skipRedisSync: boolean = false
): [T, (value: T | ((prev: T) => T)) => void] {
    const getComponentProxy = skipRedisSync ? getLocalComponentValtio : getCachedComponentValtio;
    let componentProxy = getComponentProxy(valtio_path);
    const idbKey = `${valtio_path}:${key}`;
    const getFreshComponentProxy = () => getComponentProxy(valtio_path);

    if (!componentProxy.state) {
        componentProxy.state = {};
    }

    // ── Refs ──────────────────────────────────────────────────────────────
    // localStateRef: synchronous source of truth. Updated by BOTH the setter
    // and the Valtio subscription so rapid reads always see the latest value.
    // Never updated via useEffect (that was the source of the streaming bug).
    const localStateRef = useRef<T>(
        (componentProxy.state[key] as T) ?? initialValue
    );
    const timeoutRef = useRef<NodeJS.Timeout | null>(null);
    const lastUpdateRef = useRef<number>(0);
    // Guard to distinguish our own proxy writes from external ones (YJS sync)
    const isOwnWrite = useRef(false);

    // ── React state ──────────────────────────────────────────────────────
    const [localState, setLocalState] = useState<T>(
        (componentProxy.state[key] as T) ?? initialValue
    );

    // ── Scope-key resync (synchronous, in render) ────────────────────────
    // When idbKey changes without a remount (org/workflow switch, or a
    // workspace-scoped key), the useState above still holds the PREVIOUS scope's
    // value — its initializer ran once at mount, and the subscribe effect below
    // only re-syncs AFTER paint (cold: after an IndexedDB await). Re-seed from
    // the new scope's proxy here so the first painted frame is already correct.
    // Guarded so it fires once per idbKey change; static-key callers never enter
    // it. The effect still owns async hydration + re-subscription.
    const prevIdbKeyRef = useRef(idbKey);
    if (prevIdbKeyRef.current !== idbKey) {
        prevIdbKeyRef.current = idbKey;
        const seeded = (componentProxy.state[key] as T) ?? initialValue;
        localStateRef.current = seeded;
        setLocalState(seeded);
    }

    // ── Initialize from persistence & subscribe to external changes ──────
    useEffect(() => {
        const initializeState = async () => {
            if (componentProxy.state[key] === undefined) {
                const [sessionValue, idbValue] = await Promise.all([
                    valtioSessionCache.get<T>(idbKey),
                    valtioCache.get<T>(idbKey)
                ]);
                const resolved = sessionValue ?? idbValue ?? initialValue;
                if (resolved !== initialValue) {
                    componentProxy.state[key] = resolved;
                }
                localStateRef.current = resolved;
                setLocalState(resolved);
            } else {
                const existing = componentProxy.state[key] as T;
                localStateRef.current = existing;
                setLocalState(existing);
            }
        };
        initializeState();

        // Subscribe to proxy changes (from YJS sync, other components, or our own writes).
        // Our own writes are guarded by isOwnWrite to avoid redundant state updates.
        let unsubscribe: () => void;
        if (typeof componentProxy.state[key] === 'object') {
            unsubscribe = subscribe(componentProxy.state, () => {
                if (isOwnWrite.current) return;
                const val = componentProxy.state[key] as T;
                const snapshot = Array.isArray(val) ? [...val] as T
                    : (val && typeof val === 'object') ? { ...val } as T
                    : val;
                localStateRef.current = snapshot;
                setLocalState(snapshot);
            });
        } else {
            unsubscribe = subscribeKey(componentProxy.state, key, (val) => {
                if (isOwnWrite.current) return;
                localStateRef.current = val as T;
                setLocalState(val as T);
            });
        }
        return () => unsubscribe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, idbKey, valtio_path]);

    // ── Setter ───────────────────────────────────────────────────────────
    const setCachedValtioState = useCallback(
        (value: T | ((prev: T) => T)) => {
            // 1. Compute new value from ref (synchronous chaining for rapid updates)
            const newValue = value instanceof Function
                ? value(localStateRef.current)
                : value;

            // 2. Update ref synchronously — next setter call sees this immediately
            localStateRef.current = newValue;

            // 3. Update React state via functional update so Valtio subscription's
            //    setLocalState(directValue) can't clobber our update in the queue
            setLocalState(() => newValue);

            // 4. Persist to local storage synchronously (survives refresh)
            const serialized = JSON.parse(JSON.stringify(newValue));
            valtioSessionCache.set(idbKey, serialized);
            valtioCache.set(idbKey, serialized);

            // 5. Update Valtio proxy (guarded to skip our own subscription echo)
            isOwnWrite.current = true;
            try {
                const freshProxy = getFreshComponentProxy();
                if (!skipRedisSync) {
                    if (timeoutRef.current) clearTimeout(timeoutRef.current);
                    const RATE_LIMIT_MS = 100;
                    const now = Date.now();
                    if (now - lastUpdateRef.current >= RATE_LIMIT_MS) {
                        freshProxy.state[key] = newValue;
                        lastUpdateRef.current = now;
                    } else {
                        const captured = newValue;
                        timeoutRef.current = setTimeout(() => {
                            isOwnWrite.current = true;
                            try {
                                getFreshComponentProxy().state[key] = captured;
                            } finally {
                                isOwnWrite.current = false;
                            }
                            lastUpdateRef.current = Date.now();
                            timeoutRef.current = null;
                        }, RATE_LIMIT_MS);
                    }
                } else {
                    freshProxy.state[key] = newValue;
                }
            } finally {
                isOwnWrite.current = false;
            }
        },
        [componentProxy, key, idbKey, skipRedisSync]
    );

    useEffect(() => {
        return () => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, []);

    return [localState, setCachedValtioState];
}
