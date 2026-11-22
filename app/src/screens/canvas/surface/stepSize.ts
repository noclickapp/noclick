// How big a step is on the canvas, for placing a new one beside it and for laying a workflow out: its measured size
// once it's drawn, else what its type's drawing declares (the canvas's `canvas.step.drawing`: a host's node definitions,
// or the catalog the host loaded), else a plain step's.
import type { Node } from '@xyflow/react';
import { DEFAULT_NODE_HEIGHT, DEFAULT_NODE_WIDTH } from '@/lib/nodeSizes';
import { standing } from '@/slots';
import type { NodeDimensions } from '../nodes/types';
import { STEP_DRAWING } from '../slots';

export interface StepSize {
    width: number;
    height: number;
}

/** A step type's size as its drawing declares it; undefined where it declares none. */
export function stepDimensions(type: string): NodeDimensions | undefined {
    const drawing = standing(STEP_DRAWING);
    return drawing.outline(type)?.dimensions ?? drawing.definition(type)?.dimensions;
}

/** The box of a step type that isn't on the canvas yet (nothing to measure). */
export function typeSize(type: string | undefined): StepSize {
    const dimensions = type ? stepDimensions(type) : undefined;
    return dimensions ? { width: dimensions.width, height: dimensions.height } : { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
}

/** The box of a step on the canvas: as React Flow measured it once drawn, else its type's. */
export function nodeSize(node: Node): StepSize {
    const measured = node.measured;
    if (measured?.width && measured?.height) return { width: measured.width, height: measured.height };
    return typeSize(node.type);
}
