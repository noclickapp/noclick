// Builds asked for while the builder panel isn't drawn (a host that loads it only once opened): held here, light, for
// the panel to start once it's there. The panel says when it is, so a request reaches it once, never twice.
import { useSyncExternalStore } from 'react';

let mounted = 0;
const held: string[] = [];

/** The panel is drawn (its return: no longer). */
export function panelMounted(): () => void {
    mounted += 1;
    return () => void (mounted -= 1);
}

/** Whether a panel is drawn now, hearing requests itself. */
export function panelListening(): boolean {
    return mounted > 0;
}

/** Holds `prompt` for the panel to start once it's drawn. */
export function holdRequest(prompt: string): void {
    held.push(prompt);
}

/** The requests held for the panel, taken once. */
export function takeHeld(): string[] {
    return held.splice(0, held.length);
}

/** Told on `document` as a workflow's build starts and stops working (`{workflowId, working}`), so its canvas can
 *  tell a build's test run from the person's own. */
export const WORKING_EVENT = 'noclick:builder:working';

const building = new Set<string>();

export function tellWorking(workflowId: string, working: boolean): void {
    if (working) building.add(workflowId);
    else building.delete(workflowId);
    document.dispatchEvent(new CustomEvent(WORKING_EVENT, { detail: { workflowId, working } }));
}

/** Whether a build of `workflowId` is working now. */
export function isBuilding(workflowId: string | null | undefined): boolean {
    return !!workflowId && building.has(workflowId);
}

function subscribe(changed: () => void): () => void {
    document.addEventListener(WORKING_EVENT, changed);
    return () => document.removeEventListener(WORKING_EVENT, changed);
}

/** `isBuilding`, read in a component (drawn again as it changes). */
export function useBuilding(workflowId: string | null | undefined): boolean {
    return useSyncExternalStore(subscribe, () => isBuilding(workflowId), () => false);
}
