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

// AI editing state - tracks which nodes are being modified
let _editingNodeIds: Set<string> = new Set();
let _isAiEditing: boolean = false;

// Detailed edit info per node for animated editing view
export interface NodeEditInfo {
    status: 'processing' | 'complete';
    action: 'added' | 'removed' | 'updated';
    operation?: string;
    config?: Record<string, any>;
}
let _nodeEditInfo: Map<string, NodeEditInfo> = new Map();

export function setEditingNodeIds(nodeIds: Set<string>) {
    _editingNodeIds = nodeIds;
    _listeners.forEach(listener => listener());
}

export function getEditingNodeIds(): Set<string> {
    return _editingNodeIds;
}

export function setIsAiEditing(isEditing: boolean) {
    _isAiEditing = isEditing;
    // Clear edit info when editing stops
    if (!isEditing) {
        _nodeEditInfo.clear();
    }
    _listeners.forEach(listener => listener());
}

export function getIsAiEditing(): boolean {
    return _isAiEditing;
}

export function isNodeBeingEdited(nodeId: string): boolean {
    return _editingNodeIds.has(nodeId);
}

// Node edit info management
export function setNodeEditInfo(nodeId: string, info: NodeEditInfo) {
    _nodeEditInfo.set(nodeId, info);
    _listeners.forEach(listener => listener());
}

export function updateNodeEditInfo(nodeId: string, partial: Partial<NodeEditInfo>) {
    const existing = _nodeEditInfo.get(nodeId);
    if (existing) {
        // Merge config fields instead of replacing
        const mergedConfig = partial.config
            ? { ...(existing.config || {}), ...partial.config }
            : existing.config;
        _nodeEditInfo.set(nodeId, { ...existing, ...partial, config: mergedConfig });
    } else {
        _nodeEditInfo.set(nodeId, {
            status: 'processing',
            action: 'updated',
            ...partial,
        } as NodeEditInfo);
    }
    _listeners.forEach(listener => listener());
}

export function getNodeEditInfo(nodeId: string): NodeEditInfo | undefined {
    return _nodeEditInfo.get(nodeId);
}

export function clearNodeEditInfo(nodeId: string) {
    _nodeEditInfo.delete(nodeId);
    _listeners.forEach(listener => listener());
}

export function clearAllNodeEditInfo() {
    _nodeEditInfo.clear();
    _listeners.forEach(listener => listener());
}

// Remote AI editing state - tracks which nodes are being edited by remote collaborators
interface RemoteAiEditingState {
    userId: string;
    userName?: string;
    nodeIds: Set<string>;
    nodeInfo: Map<string, NodeEditInfo>;
}
let _remoteAiEditing: Map<string, RemoteAiEditingState> = new Map();

export function setRemoteAiEditing(userId: string, nodeIds: string[], userName?: string) {
    _remoteAiEditing.set(userId, {
        userId,
        userName,
        nodeIds: new Set(nodeIds),
        nodeInfo: new Map(),
    });
    _listeners.forEach(listener => listener());
}

export function updateRemoteAiEditingInfo(userId: string, nodeId: string, info: NodeEditInfo) {
    const state = _remoteAiEditing.get(userId);
    if (state) {
        state.nodeInfo.set(nodeId, info);
        // Also add to nodeIds if not already present
        state.nodeIds.add(nodeId);
        _listeners.forEach(listener => listener());
    }
}

export function clearRemoteAiEditing(userId: string) {
    _remoteAiEditing.delete(userId);
    _listeners.forEach(listener => listener());
}

export function getRemoteAiEditing(): Map<string, RemoteAiEditingState> {
    return _remoteAiEditing;
}

/**
 * Check if a node is being edited by a remote collaborator.
 * Returns the collaborator info and edit info if found, null otherwise.
 */
export function isNodeBeingEditedByRemote(nodeId: string): { userId: string; userName?: string; info?: NodeEditInfo } | null {
    for (const [userId, state] of _remoteAiEditing) {
        if (state.nodeIds.has(nodeId)) {
            return {
                userId,
                userName: state.userName,
                info: state.nodeInfo.get(nodeId),
            };
        }
    }
    return null;
}

/**
 * Check if any remote collaborator is currently AI editing.
 */
export function isAnyRemoteAiEditing(): boolean {
    return _remoteAiEditing.size > 0;
}

// Pending node selection - used when navigating from ChatBox or deep links to select a specific node
let _pendingNodeSelection: { workflowId: string; nodeId: string; fieldKey?: string } | null = null;

export function setPendingNodeSelection(workflowId: string, nodeId: string, fieldKey?: string) {
    _pendingNodeSelection = { workflowId, nodeId, fieldKey };
}

// Peek at pending selection without consuming it
export function getPendingNodeSelection(): { workflowId: string; nodeId: string; fieldKey?: string } | null {
    return _pendingNodeSelection;
}

// Clear the pending selection (call after successfully processing)
export function clearPendingNodeSelection(): void {
    _pendingNodeSelection = null;
}

// Legacy function - consumes and returns in one call
export function consumePendingNodeSelection(): { workflowId: string; nodeId: string; fieldKey?: string } | null {
    const selection = _pendingNodeSelection;
    _pendingNodeSelection = null;
    return selection;
}
