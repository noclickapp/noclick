// Whether the canvas a step is drawn on is only looked at (a run's replay, a workflow its viewer may only view), as the
// surface tells the steps inside it: a step then shows none of what changes it (its delete, its next-step hint, its
// run and pin pills).
import { createContext, useContext } from 'react';

export const CanvasFrozen = createContext(false);

export function useCanvasFrozen(): boolean {
    return useContext(CanvasFrozen);
}
