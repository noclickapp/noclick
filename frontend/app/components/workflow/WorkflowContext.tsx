// Global store for providing workflow-level information to child components.
// Uses a module-level variable instead of React Context because ReactFlow's
// internal node rendering doesn't reliably propagate context to custom nodes.

import { createContext, useContext, ReactNode, useEffect } from 'react';

// Module-level store for current workflow info
// This is more reliable than React Context for ReactFlow nodes
let _currentWorkflowId: string | undefined;
let _currentWorkflowName: string | undefined;
const _listeners: Set<() => void> = new Set();

export function setCurrentWorkflowId(id: string | undefined) {
    _currentWorkflowId = id;
    // Notify listeners (for any components that want to re-render on change)
    _listeners.forEach(listener => listener());
}

export function getCurrentWorkflowId(): string | undefined {
    return _currentWorkflowId;
}

export function setCurrentWorkflowName(name: string | undefined) {
    _currentWorkflowName = name;
    _listeners.forEach(listener => listener());
}

export function getCurrentWorkflowName(): string | undefined {
    return _currentWorkflowName;
}

// React Context (kept for compatibility, but may not work with ReactFlow nodes)
interface WorkflowContextType {
    workflowId: string | undefined;
    workflowName: string | undefined;
}

const WorkflowContext = createContext<WorkflowContextType>({ workflowId: undefined, workflowName: undefined });

export function WorkflowProvider({ workflowId, workflowName, children }: { workflowId: string | undefined; workflowName: string | undefined; children: ReactNode }) {
    // Update the global store when workflow info changes
    useEffect(() => {
        setCurrentWorkflowId(workflowId);
        setCurrentWorkflowName(workflowName);
        return () => {
            // Clear when component unmounts
            setCurrentWorkflowId(undefined);
            setCurrentWorkflowName(undefined);
        };
    }, [workflowId, workflowName]);

    return (
        <WorkflowContext.Provider value={{ workflowId, workflowName }}>
            {children}
        </WorkflowContext.Provider>
    );
}

// Hook that tries context first, falls back to global store
export function useWorkflowId(): string | undefined {
    const contextValue = useContext(WorkflowContext).workflowId;
    // If context has a value, use it; otherwise fall back to global store
    return contextValue || getCurrentWorkflowId();
}

export function useWorkflowName(): string | undefined {
    const contextValue = useContext(WorkflowContext).workflowName;
    return contextValue || getCurrentWorkflowName();
}

// Pending node selection - used when navigating from ChatBox to select a specific node
let _pendingNodeSelection: { workflowId: string; nodeId: string } | null = null;

export function setPendingNodeSelection(workflowId: string, nodeId: string) {
    _pendingNodeSelection = { workflowId, nodeId };
}

// Peek at pending selection without consuming it
export function getPendingNodeSelection(): { workflowId: string; nodeId: string } | null {
    return _pendingNodeSelection;
}

// Clear the pending selection (call after successfully processing)
export function clearPendingNodeSelection(): void {
    _pendingNodeSelection = null;
}

// Legacy function - consumes and returns in one call
export function consumePendingNodeSelection(): { workflowId: string; nodeId: string } | null {
    const selection = _pendingNodeSelection;
    _pendingNodeSelection = null;
    return selection;
}
