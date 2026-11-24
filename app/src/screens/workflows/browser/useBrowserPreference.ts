// A view preference of the Automations page (cards or rows, whose automations), kept per browser and workspace in
// local storage: a local choice, never the account's.
import { useCallback, useState } from 'react';

const read = <T extends string>(key: string, fallback: T): T => {
    try {
        return (localStorage.getItem(key) as T | null) ?? fallback;
    } catch {
        return fallback;
    }
};

export function useBrowserPreference<T extends string>(scopeId: string, name: string, fallback: T): [T, (value: T) => void] {
    const key = `noclick:workflows:${scopeId}:${name}`;
    const [held, setHeld] = useState<{ key: string; value: T }>(() => ({ key, value: typeof window === 'undefined' ? fallback : read(key, fallback) }));
    // Another workspace's preference is read as the page moves to it.
    const value = held.key === key ? held.value : read(key, fallback);
    const set = useCallback(
        (next: T) => {
            setHeld({ key, value: next });
            try {
                localStorage.setItem(key, next);
            } catch {
                // Storage refused (private mode): the choice holds for this page.
            }
        },
        [key]
    );
    return [value, set];
}
