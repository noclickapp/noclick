// A resizable column's width: dragged from its edge within a small range,
// remembered on this device, and read by everything laid out beside it. One
// store per column (the app sidebar, the channel list), each with its own key.
import { useSyncExternalStore } from 'react';

export interface PanelWidth {
    readonly initial: number;
    readonly min: number;
    readonly max: number;
    clamp(value: number): number;
    set(next: number): void;
    setResizing(next: boolean): void;
    /** The width; the server renders `initial` and the client catches up. */
    useWidth(): number;
    /** True while the edge is being dragged, so neighbours follow without easing. */
    useResizing(): boolean;
}

export function createPanelWidth({ key, initial, min, max }: { key: string; initial: number; min: number; max: number }): PanelWidth {
    const clamp = (value: number) => Math.min(max, Math.max(min, Math.round(value)));
    const stored = (): number => {
        if (typeof window === 'undefined') return initial;
        try {
            const value = Number(window.localStorage.getItem(key));
            return value ? clamp(value) : initial;
        } catch {
            // Storage blocked (private window, embedded preview): the default stands.
            return initial;
        }
    };

    let width = stored();
    let resizing = false;
    const listeners = new Set<() => void>();
    const emit = () => listeners.forEach((listener) => listener());
    const subscribe = (listener: () => void) => {
        listeners.add(listener);
        return () => {
            listeners.delete(listener);
        };
    };

    function useWidth(): number {
        return useSyncExternalStore(subscribe, () => width, () => initial);
    }
    function useResizing(): boolean {
        return useSyncExternalStore(subscribe, () => resizing, () => false);
    }

    return {
        initial,
        min,
        max,
        clamp,
        set(next) {
            width = clamp(next);
            try {
                window.localStorage.setItem(key, String(width));
            } catch {
                // Not remembered this time; the width still applies.
            }
            emit();
        },
        setResizing(next) {
            resizing = next;
            emit();
        },
        useWidth,
        useResizing,
    };
}
