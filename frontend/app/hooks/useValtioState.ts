// Hook for using local valtio state (not synced with backend)
// This is the default for better performance - use useCachedValtioState for persistence
import { subscribe } from 'valtio';
import { useCallback, useState, useEffect, useRef } from 'react';
import { getLocalComponentValtio } from '~/state';
import { subscribeKey } from 'valtio/utils';

/**
 * A wrapper around valtio for local-only state without backend sync
 * This is the default hook for better performance - no debouncing needed
 * @param valtio_path The path to the component in the valtio state tree
 * @param key The key in the proxy object where the state will be stored
 * @param initialValue The initial value for the state
 * @returns A tuple containing the state value and a setter function
 */
export function useValtioState<T = any>(
    valtio_path: string,
    key: string,
    initialValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
    // Parse path and get the correct proxy from local state
    let componentProxy = getLocalComponentValtio(valtio_path);

    // Initialize the state object if it doesn't exist
    // Can be missing after YJS binding syncs partial state (same pattern as subcomponents in state.ts)
    if (!componentProxy.state) {
        componentProxy.state = {};
    }

    const createStateSnapshot = (value: T): T => {
        if (Array.isArray(value)) {
            return [...value] as T;
        } else if (value && typeof value === 'object') {
            return { ...value } as T;
        }
        return value;
    };

    const setupValtioSyncer = () => {
        // For primitive types, use subscribeKey (most efficient)
        // For objects, we still need to subscribe to componentProxy.state since the object
        // may not exist yet during setup (it gets initialized in useEffect)
        let unsubscribeKey: () => void;
        if (typeof componentProxy.state[key] === 'object') {
            unsubscribeKey = subscribe(componentProxy.state, () => {
                // Skip if this update came from our own setter (avoids redundant snapshot + setState)
                if (isLocalUpdateRef.current) { isLocalUpdateRef.current = false; return; }
                setLocalState(createStateSnapshot(componentProxy.state[key] as T));
            });
        } else {
            unsubscribeKey = subscribeKey(
                componentProxy.state,
                key,
                (value) => {
                    if (isLocalUpdateRef.current) { isLocalUpdateRef.current = false; return; }
                    setLocalState(value as T);
                }
            );
        }
        return unsubscribeKey;
    };

    // Use ref to track proxy for detecting reference changes (avoid creating subscription on every render)
    const componentProxyRef = useRef(componentProxy);
    // Guard to skip subscription callback when update came from our own setter
    const isLocalUpdateRef = useRef(false);

    // Get snapshot of the entire proxy
    const [localState, setLocalState] = useState<T>(() => {
        // Initialize with value from proxy or initialValue
        const currentValue = componentProxy.state[key] as T;

        // In development, warn if we're getting undefined when we shouldn't be
        if (process.env.NODE_ENV === 'development' && currentValue === undefined && initialValue !== undefined) {
            console.warn(
                `[useValtioState] Initializing '${key}' at path '${valtio_path}' with default value. ` +
                `This might indicate a timing issue where state is accessed before initialization.`
            );
        }

        return currentValue ?? initialValue;
    });

    // Initialize the specific key if it doesn't exist and handle external valtio changes
    useEffect(() => {
        // Initialize if needed
        if (componentProxy.state[key] === undefined) {
            componentProxy.state[key] = initialValue;
            setLocalState(initialValue);
        }

        // Subscribe to key-specific changes
        const unsubscribeKey = setupValtioSyncer();

        // NOTE: We intentionally do NOT subscribe to root state for proxy reference changes.
        // Root subscription fires on EVERY valtio change app-wide, causing significant overhead.
        // Proxy reference changes (e.g., YJS binding) are rare and handled by:
        // 1. The key-specific subscription which fires on any changes to our componentProxy
        // 2. Fresh proxy lookup in the setter via getLocalComponentValtio

        return () => {
            unsubscribeKey();
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, initialValue, valtio_path]); // componentProxy.state and setupValtioSyncer omitted for performance

    // Create setter function that updates local state immediately (no debouncing)
    const setValtioState = useCallback(
        (value: T | ((prev: T) => T)) => {
            // Get fresh proxy reference to handle cases where proxy might have changed
            const freshProxy = getLocalComponentValtio(valtio_path);
            const currentValue = freshProxy.state[key] as T;
            const newValue =
                value instanceof Function ? value(currentValue) : value;

            // Update both React state and valtio proxy immediately
            setLocalState(newValue);
            isLocalUpdateRef.current = true;
            freshProxy.state[key] = newValue;
        },
        [valtio_path, key]
    );

    // Log error if localState is undefined when it shouldn't be
    // This catches race conditions where state is accessed before initialization completes
    if (localState === undefined && initialValue !== undefined) {
        console.error(
            `[useValtioState] CRITICAL: State '${key}' at path '${valtio_path}' is undefined when it should be initialized. ` +
            `This indicates a race condition where the component is rendering before state initialization completes. ` +
            `Expected initial value type: ${typeof initialValue}. ` +
            `Make sure state.ts module is loaded before components that use it render.`
        );
    }

    return [localState, setValtioState];
}
