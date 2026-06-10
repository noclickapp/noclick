// Global store for providing workflow-level information to child components.
// Uses a Valtio proxy (hoisted to globalThis to survive Vite HMR) instead of
// React Context because ReactFlow's internal node rendering doesn't reliably
// propagate context to custom nodes — every node would need to be wrapped in
// a context consumer, and ReactFlow re-mounts nodes aggressively.
//
// The proxy is the single source of truth. React components consume it via
// useSnapshot() (or the typed selector hooks at the bottom of this file);
// non-React callers mutate it via the setter functions below.

import { createContext, useContext, ReactNode, useEffect } from 'react';
import { proxy, useSnapshot } from 'valtio';
import { builderContextStore, updateBuilderContext } from '~/lib/builder-context';

// Detailed edit info per node for animated editing view. Exported because
// callers (FlowCanvas, edit overlays) construct values of this shape.
export interface NodeEditInfo {
    status: 'processing' | 'complete';
    action: 'added' | 'removed' | 'updated';
    operation?: string;
    config?: Record<string, any>;
}

interface RemoteAiEditingState {
    userId: string;
    userName?: string;
    nodeIds: Set<string>;
    nodeInfo: Map<string, NodeEditInfo>;
}

interface WorkflowEditorStore {
    /** Workflow id of the currently-mounted editor. undefined when no editor mounted. */
    currentWorkflowId: string | undefined;
    currentWorkflowName: string | undefined;
    /** Node ids currently being edited by the local AI run. */
    editingNodeIds: Set<string>;
    /** Whether the local AI run is mid-edit. */
    isAiEditing: boolean;
    /** Per-node edit metadata for the animated editing overlay. */
    nodeEditInfo: Map<string, NodeEditInfo>;
    /** Per-collaborator AI editing state for live collaboration. */
    remoteAiEditing: Map<string, RemoteAiEditingState>;
    /** Pending node selection injected by ChatBox / deep links. */
    pendingNodeSelection: { workflowId: string; nodeId: string; fieldKey?: string } | null;
}

const INITIAL: WorkflowEditorStore = {
    currentWorkflowId: undefined,
    currentWorkflowName: undefined,
    editingNodeIds: new Set(),
    isAiEditing: false,
    nodeEditInfo: new Map(),
    remoteAiEditing: new Map(),
    pendingNodeSelection: null,
};

// HMR-safe singleton. See builder-context.ts for the rationale.
const GLOBAL_KEY = '__ncWorkflowEditorProxy';

function getOrCreateStore(): WorkflowEditorStore {
    if (typeof window === 'undefined') return proxy({ ...INITIAL });
    const w = window as unknown as { [GLOBAL_KEY]?: WorkflowEditorStore };
    if (!w[GLOBAL_KEY]) w[GLOBAL_KEY] = proxy({ ...INITIAL });
    return w[GLOBAL_KEY];
}

/**
 * The workflow-editor proxy. Mutate directly; Valtio handles change detection
 * and notifies React subscribers via useSnapshot. Non-React consumers can
 * read this directly or use the get* helpers below.
 */
export const workflowEditorStore: WorkflowEditorStore = getOrCreateStore();

// ── Current workflow id / name ──────────────────────────────────────────────

export function setCurrentWorkflowId(id: string | undefined) {
    workflowEditorStore.currentWorkflowId = id;
    if (id) {
        // Persist so headless builder can access after canvas unmounts
        updateBuilderContext({ workflowId: id, isCanvasMounted: true });
    } else {
        updateBuilderContext({ isCanvasMounted: false });
        // DON'T clear builder-context.workflowId — keep it for headless builder
    }
}

export function getCurrentWorkflowId(): string | undefined {
    return workflowEditorStore.currentWorkflowId;
}

export function setCurrentWorkflowName(name: string | undefined) {
    workflowEditorStore.currentWorkflowName = name;
    if (name) updateBuilderContext({ workflowName: name });
}

export function getCurrentWorkflowName(): string | undefined {
    return workflowEditorStore.currentWorkflowName;
}

// ── React Context (legacy, retained for API compatibility) ─────────────────

interface WorkflowContextType {
    workflowId: string | undefined;
    workflowName: string | undefined;
}

const WorkflowContext = createContext<WorkflowContextType>({ workflowId: undefined, workflowName: undefined });

export function WorkflowProvider({ workflowId, workflowName, children }: { workflowId: string | undefined; workflowName: string | undefined; children: ReactNode }) {
    useEffect(() => {
        setCurrentWorkflowId(workflowId);
        setCurrentWorkflowName(workflowName);
        return () => {
            // Clear on unmount so consumers know the editor is no longer mounted.
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
    return contextValue || getCurrentWorkflowId();
}

export function useWorkflowName(): string | undefined {
    const contextValue = useContext(WorkflowContext).workflowName;
    return contextValue || getCurrentWorkflowName();
}

// ── Reactive selector hooks ─────────────────────────────────────────────────

/**
 * Currently-mounted workflow editor id. Returns undefined the moment
 * WorkflowProvider unmounts — the right signal for "is the user actively
 * looking at a workflow editor right now". Don't confuse with
 * builder-context.workflowId, which is intentionally sticky for headless flows.
 */
export function useActiveWorkflowEditorId(): string | undefined {
    return useSnapshot(workflowEditorStore).currentWorkflowId;
}

export function useActiveWorkflowEditorName(): string | undefined {
    return useSnapshot(workflowEditorStore).currentWorkflowName;
}

/**
 * "Effective" workflow id: prefers the canvas-mounted store, falls back to
 * builder-context's persisted workflowId for headless flows. Used by the
 * sidebar where "current workflow" should also reflect headless-builder edits
 * that don't mount a canvas.
 *
 * Subscribes to BOTH proxies via useSnapshot so we re-render whenever either
 * source changes. Valtio's per-key tracking means this is cheap — we only
 * actually re-render when one of the two reads materializes a new value.
 */
export function useEffectiveWorkflowId(): string | undefined {
    const editorId = useSnapshot(workflowEditorStore).currentWorkflowId;
    const fallbackId = useSnapshot(builderContextStore).workflowId;
    return editorId ?? fallbackId ?? undefined;
}

export function useEffectiveWorkflowName(): string | undefined {
    const editorName = useSnapshot(workflowEditorStore).currentWorkflowName;
    const fallbackName = useSnapshot(builderContextStore).workflowName;
    return editorName ?? fallbackName ?? undefined;
}

// ── AI editing state ────────────────────────────────────────────────────────

export function setEditingNodeIds(nodeIds: Set<string>) {
    workflowEditorStore.editingNodeIds = nodeIds;
}

export function getEditingNodeIds(): Set<string> {
    return workflowEditorStore.editingNodeIds;
}

export function setIsAiEditing(isEditing: boolean) {
    workflowEditorStore.isAiEditing = isEditing;
    if (!isEditing) workflowEditorStore.nodeEditInfo.clear();
}

export function getIsAiEditing(): boolean {
    return workflowEditorStore.isAiEditing;
}

export function isNodeBeingEdited(nodeId: string): boolean {
    return workflowEditorStore.editingNodeIds.has(nodeId);
}

// ── Per-node edit info ──────────────────────────────────────────────────────

export function setNodeEditInfo(nodeId: string, info: NodeEditInfo) {
    workflowEditorStore.nodeEditInfo.set(nodeId, info);
}

export function updateNodeEditInfo(nodeId: string, partial: Partial<NodeEditInfo>) {
    const map = workflowEditorStore.nodeEditInfo;
    const existing = map.get(nodeId);
    if (existing) {
        const mergedConfig = partial.config
            ? { ...(existing.config || {}), ...partial.config }
            : existing.config;
        map.set(nodeId, { ...existing, ...partial, config: mergedConfig });
    } else {
        map.set(nodeId, {
            status: 'processing',
            action: 'updated',
            ...partial,
        } as NodeEditInfo);
    }
}

export function getNodeEditInfo(nodeId: string): NodeEditInfo | undefined {
    return workflowEditorStore.nodeEditInfo.get(nodeId);
}

export function clearNodeEditInfo(nodeId: string) {
    workflowEditorStore.nodeEditInfo.delete(nodeId);
}

export function clearAllNodeEditInfo() {
    workflowEditorStore.nodeEditInfo.clear();
}

// ── Remote AI editing (live collaboration) ──────────────────────────────────

export function setRemoteAiEditing(userId: string, nodeIds: string[], userName?: string) {
    workflowEditorStore.remoteAiEditing.set(userId, {
        userId,
        userName,
        nodeIds: new Set(nodeIds),
        nodeInfo: new Map(),
    });
}

export function updateRemoteAiEditingInfo(userId: string, nodeId: string, info: NodeEditInfo) {
    const state = workflowEditorStore.remoteAiEditing.get(userId);
    if (state) {
        state.nodeInfo.set(nodeId, info);
        state.nodeIds.add(nodeId);
    }
}

export function clearRemoteAiEditing(userId: string) {
    workflowEditorStore.remoteAiEditing.delete(userId);
}

export function getRemoteAiEditing(): Map<string, RemoteAiEditingState> {
    return workflowEditorStore.remoteAiEditing;
}

export function isNodeBeingEditedByRemote(nodeId: string): { userId: string; userName?: string; info?: NodeEditInfo } | null {
    for (const [userId, state] of workflowEditorStore.remoteAiEditing) {
        if (state.nodeIds.has(nodeId)) {
            return { userId, userName: state.userName, info: state.nodeInfo.get(nodeId) };
        }
    }
    return null;
}

export function isAnyRemoteAiEditing(): boolean {
    return workflowEditorStore.remoteAiEditing.size > 0;
}

// ── Pointer-driven delete ───────────────────────────────────────────────────
// The post-delete selection-move autopan is helpful for keyboard deletes (the
// user's focus follows the selection) but distracting for mouse deletes (the
// cursor is already where the user is looking). The delete pill marks its
// deletes here; FlowCanvas's remove handler consumes the mark and keeps the
// selection move while skipping the pan.

let pointerDeleteAt = 0;

export function markPointerDrivenDelete(): void {
    pointerDeleteAt = Date.now();
}

export function consumePointerDrivenDelete(): boolean {
    const recent = Date.now() - pointerDeleteAt < 500;
    pointerDeleteAt = 0;
    return recent;
}

// ── Pending node selection ──────────────────────────────────────────────────

export function setPendingNodeSelection(workflowId: string, nodeId: string, fieldKey?: string) {
    workflowEditorStore.pendingNodeSelection = { workflowId, nodeId, fieldKey };
}

export function getPendingNodeSelection(): { workflowId: string; nodeId: string; fieldKey?: string } | null {
    return workflowEditorStore.pendingNodeSelection;
}

export function clearPendingNodeSelection(): void {
    workflowEditorStore.pendingNodeSelection = null;
}

export function consumePendingNodeSelection(): { workflowId: string; nodeId: string; fieldKey?: string } | null {
    const selection = workflowEditorStore.pendingNodeSelection;
    workflowEditorStore.pendingNodeSelection = null;
    return selection;
}
