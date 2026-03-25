// Tracks what the user is currently looking at (tab, workflow, selected node/block).
// Used by the headless builder and NoClick chat to make context-aware routing decisions.

export interface BuilderContext {
    /** Dashboard-level tab: 'flow' | 'feed' | 'debug' | 'analytics' | 'settings' */
    dashboardTab: string | null;
    /** Current workflow ID (persists after canvas unmount) */
    workflowId: string | null;
    /** Current workflow name */
    workflowName: string | null;
    /** Inner workflow tab: 'canvas' | 'interface' | 'logs' | 'setup' | 'resources' */
    innerTab: string | null;
    /** Selected node on canvas */
    selectedNodeId: string | null;
    /** Selected block on interface grid */
    selectedInterfaceBlockId: string | null;
    /** Whether FlowCanvas is actively mounted */
    isCanvasMounted: boolean;
}

const _context: BuilderContext = {
    dashboardTab: null,
    workflowId: null,
    workflowName: null,
    innerTab: null,
    selectedNodeId: null,
    selectedInterfaceBlockId: null,
    isCanvasMounted: false,
};

export function getBuilderContext(): Readonly<BuilderContext> {
    return _context;
}

export function updateBuilderContext(partial: Partial<BuilderContext>): void {
    Object.assign(_context, partial);
}
