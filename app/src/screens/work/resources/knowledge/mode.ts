// What a skill's or memory's page is doing, kept apart from both its head and its body so either can start it: a
// skill's SKILL.md being edited, a memory's new entry being written. One page shows an item at a time.
import { useSyncExternalStore } from 'react';

type Mode = 'editing' | 'writing';
const modes = new Map<string, Mode>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

export function setMode(itemId: string, mode: Mode | null): void {
    if (mode) modes.set(itemId, mode);
    else modes.delete(itemId);
    listeners.forEach((l) => l());
}

export function useMode(itemId: string): Mode | null {
    return useSyncExternalStore(
        subscribe,
        () => modes.get(itemId) ?? null,
        () => null
    );
}
