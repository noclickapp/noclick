// The richer read-only canvas a host draws a thread's agents and workflows with, in place of the SVG preview. Apart
// from canvas.tsx, which carries the preview, so registering costs nothing on the pages that never draw one.
import type { ComponentType } from 'react';
import type { SavedGraph } from '@/lib/graphPreview';

export interface CanvasProps {
    blob: SavedGraph;
    className?: string;
}

let Registered: ComponentType<CanvasProps> | null = null;

export function registerCoordinatorCanvas(canvas: ComponentType<CanvasProps>): void {
    Registered = canvas;
}

export function registeredCoordinatorCanvas(): ComponentType<CanvasProps> | null {
    return Registered;
}
