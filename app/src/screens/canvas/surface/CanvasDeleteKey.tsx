// Backspace removes the selected steps and connections, as React Flow's own delete key did, but only while the canvas
// has the keyboard: never from a field, a dialog or anything drawn beside the canvas (a step's panel), and not after
// focus was taken from a field the person was in (a dialog opening over it, the field drawn again) until they point at
// something, since the keys that follow were meant for that field. A removal of several steps offers them back.
import { useEffect, useRef } from 'react';
import { useReactFlow, useStoreApi } from '@xyflow/react';
import { toast } from 'sonner';
import { isTextEntryTarget } from '@/lib/keyboard';

/** Where focus means the keys aren't the canvas's, even inside it (React Flow's own `nokey`). */
const KEYS_ELSEWHERE = '.nokey, select, [role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]';
/** Keys that leave a field on purpose. */
const LEAVES_FIELD = new Set(['Tab', 'Escape', 'Enter']);

/** Whether a Backspace should remove the selected steps: the canvas or the page itself has the keyboard, no field was
 *  left without the person's say (`fieldHeld`) and nothing of the host's holds the keys (`held`). */
export function canvasTakesDelete(event: KeyboardEvent, fieldHeld: boolean, held?: () => boolean): boolean {
    if (event.key !== 'Backspace' || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return false;
    if (fieldHeld || held?.()) return false;
    for (const at of [event.target, document.activeElement]) {
        if (!(at instanceof Element) || at === document.body || at === document.documentElement) continue;
        if (isTextEntryTarget(at) || at.closest(KEYS_ELSEWHERE) || !at.closest('.react-flow')) return false;
    }
    return true;
}

export function CanvasDeleteKey({ held, undo }: { held?: () => boolean; undo?: () => void }) {
    const store = useStoreApi();
    const { deleteElements } = useReactFlow();
    const latest = useRef({ held, undo });
    latest.current = { held, undo };

    useEffect(() => {
        // In a field the person hasn't left: set as focus enters one or a key is typed in one, cleared when they point
        // at something or leave it from the keyboard (Tab, Escape, or Enter, which picks from a search and closes it).
        // Focus taken from it any other way leaves it set.
        let fieldHeld = isTextEntryTarget(document.activeElement);
        const onFocusIn = (event: FocusEvent) => {
            if (isTextEntryTarget(event.target)) fieldHeld = true;
        };
        const onPointerDown = () => {
            fieldHeld = false;
        };
        const onFieldKey = (event: KeyboardEvent) => {
            if (isTextEntryTarget(event.target)) fieldHeld = !LEAVES_FIELD.has(event.key);
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (!canvasTakesDelete(event, fieldHeld, latest.current.held)) return;
            const { nodes, edges } = store.getState();
            const removing = { nodes: nodes.filter((n) => n.selected), edges: edges.filter((e) => e.selected) };
            if (removing.nodes.length === 0 && removing.edges.length === 0) return;
            event.preventDefault();
            void deleteElements(removing);
            store.setState({ nodesSelectionActive: false });
            if (removing.nodes.length > 1 && latest.current.undo) {
                toast(`${removing.nodes.length} steps removed`, {
                    action: { label: 'Undo', onClick: () => latest.current.undo?.() },
                });
            }
        };
        document.addEventListener('focusin', onFocusIn, true);
        document.addEventListener('pointerdown', onPointerDown, true);
        document.addEventListener('keydown', onFieldKey, true);
        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('focusin', onFocusIn, true);
            document.removeEventListener('pointerdown', onPointerDown, true);
            document.removeEventListener('keydown', onFieldKey, true);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [store, deleteElements]);

    return null;
}
