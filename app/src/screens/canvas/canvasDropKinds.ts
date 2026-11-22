// The set of canvas wiring drop targets (agent body, edge midpoint "+", node
// tail "+"), kept in a dependency-free leaf. Both the canvas's drag-and-drop
// provider (collision detection) and CanvasDropTarget (the droppable itself) need
// these, and having the provider import them from the component made a circular
// import.

// Dropping a palette node onto one of these wires it up instead of placing it
// standalone. The canvas's drop handler branches on these exact strings.
export type CanvasDropKind =
    | 'agent-tools-drop'
    | 'edge-insert-drop'
    | 'node-tail-drop';

export const CANVAS_DROP_KINDS: ReadonlySet<string> = new Set<CanvasDropKind>([
    'agent-tools-drop',
    'edge-insert-drop',
    'node-tail-drop',
]);
