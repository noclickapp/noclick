// Raw socket event recorded during AI workflow generation/editing.
// Used by useCanvasWorkflowEdit for replay/debug tooling (workflow diagnostics).
export interface RecordedEvent {
    /** Milliseconds since generation started */
    timestamp: number;
    /** Event type from socket (e.g., 'node_start', 'edge_added') */
    eventType: string;
    /** Full event data payload */
    eventData: any;
}
