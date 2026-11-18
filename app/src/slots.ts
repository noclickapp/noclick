// Slots: named places in the app's screens that whoever renders the app may fill.
//
// A screen declares a slot beside itself (`screens/<name>/slots.ts`) with what stands there when nobody fills it, so the
// app is whole with every slot left alone. A host of these screens fills the ones it has something for, from the module
// its root imports first; a copy of this app does the same from `src/custom/` (see its README). A slot's name says
// where it is (`console.terms`: under the console's buttons that accept terms), never what a host puts there.
//
//     export const TERMS = slot<ComponentType<{ action: string }>>('console.terms', () => null);   // the screen
//     fill(TERMS, MyTermsNotice);                                                                  // a host
//     const Terms = useSlot(TERMS);                                                                // the screen
//
// A slot is typed by its own object, so a fill of the wrong shape doesn't compile. The last fill stands: a development
// server runs a filling module again on every change, and a second fill is then the same host saying the same thing.
// A fill that arrives after a page rendered (from a module loaded late) shows as soon as it lands, because `useSlot`
// follows it.
import { useSyncExternalStore } from 'react';

/** A place a host may fill: its name, and what stands there when no one has. */
export interface Slot<T> {
    readonly name: string;
    readonly standard: T;
}

// By name, not by object: a module that declares a slot may run again (a development server's reload), and the slot it
// declares then is the same place.
const declared = new Map<string, Slot<unknown>>();
const filled = new Map<string, unknown>();
const listeners = new Set<() => void>();

/** Declares the slot `name` with what stands in it by default. Names are dotted paths, screen first, and each is
 *  declared once in the source (test/slots.test.ts holds that). */
export function slot<T>(name: string, standard: T): Slot<T> {
    const made: Slot<T> = { name, standard };
    declared.set(name, made);
    return made;
}

/** Puts `value` in `slot`, in place of what stood there. */
export function fill<T>(slot: Slot<T>, value: T): void {
    filled.set(slot.name, value);
    listeners.forEach((listener) => listener());
}

/** What stands in `slot` now: its fill, else its standard. For code outside a component; a component uses `useSlot`. */
export function standing<T>(slot: Slot<T>): T {
    return filled.has(slot.name) ? (filled.get(slot.name) as T) : slot.standard;
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => void listeners.delete(listener);
}

/** What stands in `slot`, for a component: it draws again when the slot is filled. */
export function useSlot<T>(slot: Slot<T>): T {
    return useSyncExternalStore(
        subscribe,
        () => standing(slot),
        () => standing(slot),
    );
}

/** Every slot declared by the modules loaded so far, by name, and whether a host filled it: for a host's own check
 *  that it decided about each. */
export function slots(): { name: string; filled: boolean }[] {
    return [...declared.keys()].sort().map((name) => ({ name, filled: filled.has(name) }));
}
