// The richer read-only canvas a platform draws a thread's agents and workflows with (hosted: the real ReactFlow
// canvas, from cloud/bootstrap). Apart from canvas.tsx, which carries the engine's SVG preview, so registering costs
// nothing on the pages that never draw one.
import type { ComponentType } from 'react';
import type { ScaffoldBlob } from '~/lib/agentScaffold';

export interface CanvasProps {
    blob: ScaffoldBlob;
    className?: string;
}

let Registered: ComponentType<CanvasProps> | null = null;

export function registerCoordinatorCanvas(canvas: ComponentType<CanvasProps>): void {
    Registered = canvas;
}

export function registeredCoordinatorCanvas(): ComponentType<CanvasProps> | null {
    return Registered;
}
