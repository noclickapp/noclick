// Utility functions for workflow navigation (selecting and panning to nodes/edges).
// Uses custom events that are handled by FlowCanvas for reliable pan/zoom behavior.

/**
 * Navigate to a specific node in a workflow - selects it and pans/zooms to center it.
 * Dispatches a custom event that FlowCanvas listens for and handles.
 */
export function navigateToNode(workflowId: string, nodeId: string): void {
    console.log('[navigateToNode] Dispatching:', { workflowId, nodeId });
    document.dispatchEvent(new CustomEvent('noclick:workflow:select-node', {
        detail: { workflowId, nodeId }
    }));
}

/**
 * Navigate to a specific edge in a workflow - selects the connected nodes and pans to the edge.
 * Dispatches a custom event that FlowCanvas listens for and handles.
 */
export function navigateToEdge(workflowId: string, edgeId: string, sourceNodeId?: string, targetNodeId?: string): void {
    document.dispatchEvent(new CustomEvent('noclick:workflow:select-edge', {
        detail: { workflowId, edgeId, sourceNodeId, targetNodeId }
    }));
}

/**
 * Build a shareable deep link URL to a specific node (and optionally a config field) in a workflow.
 */
export function buildNodeDeepLink(workflowId: string, nodeId: string, fieldKey?: string): string {
    const url = new URL(window.location.origin + '/dashboard');
    url.searchParams.set('tab', 'workflows');
    url.searchParams.set('workflow', workflowId);
    url.searchParams.set('node', nodeId);
    if (fieldKey) {
        url.searchParams.set('field', fieldKey);
    }
    return url.toString();
}
