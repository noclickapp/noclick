// Thin React binding over the scope-keyed workflowBrowserStore. Reads the current
// scope's slice via useSnapshot and exposes the same public surface the browser
// grid / sidebar / command palette already consume, so this refactor is a
// drop-in: the fragile per-hook cache (mirror-to-useState, epoch guards, volatile
// resets, dual tree/flat-map writes, by-hand dedup) is gone — the store owns
// scope isolation by construction. See workflowBrowserStore.ts for the invariant.

import { useCallback, useEffect, useMemo } from 'react';
import { useSnapshot } from 'valtio';
import {
    browserStore,
    setCurrentScope,
    fetchTree,
    fetchWorkflows as storeFetchWorkflows,
    fetchSharedResources,
    loadAllWorkflows as storeLoadAllWorkflows,
    addWorkflow as storeAddWorkflow,
    removeWorkflow as storeRemoveWorkflow,
    removeWorkflowGlobal as storeRemoveWorkflowGlobal,
    updateWorkflow as storeUpdateWorkflow,
    moveWorkflows as storeMoveWorkflows,
    addFolder as storeAddFolder,
    removeFolder as storeRemoveFolder,
    updateFolder as storeUpdateFolder,
    moveFolders as storeMoveFolders,
    removeSharedWorkflow as storeRemoveSharedWorkflow,
    removeSharedFolder as storeRemoveSharedFolder,
    clearRemovalTombstone,
    snapshotScope,
    restoreSnapshot,
    selectTree,
    selectSubfolders,
    selectWorkflows,
    selectAllWorkflows,
    selectAllFolders,
    selectAllWorkflowsLoaded,
    selectFolderPath,
    findFolderInTree,
    wireMcpListeners,
    sweepLegacyCache,
    type TreeNode,
    type WorkflowApp,
    type FolderInfoLocal,
    type ScopeSlice,
    type SharedResources,
} from '~/lib/workflowBrowserStore';

// Re-export types + shared pure utils consumers/tests import from this module.
export type { TreeNode, WorkflowApp, FolderInfoLocal };
export {
    findFolderInTree,
    buildFolderPath,
    mapWorkflowApp,
    mapSharedWorkflowResource,
    mapSharedFolderResource,
} from '~/lib/workflowBrowserStore';

// Stable empty slice for the first render before the effect ensures the scope.
const EMPTY_SLICE = Object.freeze({
    folders: [] as TreeNode[],
    foldersLoaded: false,
    workflows: {} as Record<string, WorkflowApp[]>,
    workflowsLoading: {} as Record<string, boolean>,
    tier: 'free',
    hiddenSharedCount: 0,
});

export function useWorkflowBrowserData(scopeId: string) {
    const snap = useSnapshot(browserStore);
    // Selectors read (never mutate) the slice, so casting the deep-readonly
    // useSnapshot value to the mutable shape is sound and keeps call sites clean.
    const slice = (snap.scopes[scopeId] ?? EMPTY_SLICE) as unknown as ScopeSlice;
    const shared = snap.shared as unknown as SharedResources;

    // One-time module wiring (idempotent): MCP listeners + clear any poisoned
    // pre-refactor IndexedDB cache. The store itself is in-memory only.
    useEffect(() => {
        wireMcpListeners();
        void sweepLegacyCache();
    }, []);

    // Point the store at this scope and (SWR) refresh it. Cached data renders
    // instantly; this refetch updates it in the background. fetchTree self-dedups.
    useEffect(() => {
        setCurrentScope(scopeId);
        fetchTree(scopeId);
    }, [scopeId]);

    // ── Derived reads ────────────────────────────────────────────────────────
    const folderTree = useMemo(() => selectTree(slice), [slice]);
    const sharedWorkflows = shared.workflows;
    const sharedFolders = shared.folders;
    const workflowsByFolder = slice.workflows;

    // SWR spinner: in-flight AND the folder has never loaded (key absence, NOT
    // emptiness — a loaded-but-empty folder must not re-flash a spinner on refresh).
    const loadingWorkflows = useMemo(() => {
        const out: Record<string, boolean> = {};
        for (const key of Object.keys(slice.workflowsLoading)) {
            out[key] = slice.workflowsLoading[key] && !(key in slice.workflows);
        }
        return out;
    }, [slice.workflowsLoading, slice.workflows]);

    const getSubfolders = useCallback(
        (parentId: string | null) => selectSubfolders(slice, shared, parentId),
        [slice, shared],
    );
    const getWorkflows = useCallback(
        (folderId: string | null) => selectWorkflows(slice, shared, folderId),
        [slice, shared],
    );
    const getAllFolders = useCallback(() => selectAllFolders(slice, shared), [slice, shared]);
    const getAllWorkflows = useCallback(() => selectAllWorkflows(slice, shared), [slice, shared]);
    const getFolderPath = useCallback((folderId: string) => selectFolderPath(slice, folderId), [slice]);
    const findFolder = useCallback((folderId: string) => findFolderInTree(slice.folders, folderId), [slice]);
    // Memoized: WorkflowBrowser re-renders on every search keystroke and this walks
    // the folder tree; slice is unchanged during typing, so recompute only on data.
    const allWorkflowsLoaded = useMemo(() => selectAllWorkflowsLoaded(slice), [slice]);

    // ── Bound actions (scope captured from the prop) ─────────────────────────
    const refreshTree = useCallback(() => fetchTree(scopeId), [scopeId]);
    const refreshSharedWorkflows = useCallback(() => fetchSharedResources(), []);
    const fetchWorkflows = useCallback((folderId: string | null) => storeFetchWorkflows(scopeId, folderId), [scopeId]);
    const loadAllWorkflows = useCallback((force = false) => storeLoadAllWorkflows(scopeId, force), [scopeId]);

    const addWorkflow = useCallback(
        (folderId: string | null, workflow: WorkflowApp) => storeAddWorkflow(scopeId, folderId, workflow),
        [scopeId],
    );
    const removeWorkflow = useCallback(
        (workflowId: string, folderId: string | null) => storeRemoveWorkflow(scopeId, workflowId, folderId),
        [scopeId],
    );
    const removeWorkflowGlobal = useCallback((workflowId: string) => storeRemoveWorkflowGlobal(scopeId, workflowId), [scopeId]);
    const updateWorkflow = useCallback(
        (workflowId: string, updates: Partial<WorkflowApp>) => storeUpdateWorkflow(scopeId, workflowId, updates),
        [scopeId],
    );
    const moveWorkflows = useCallback(
        (workflowIds: string[], fromFolder: string | null, toFolder: string | null) =>
            storeMoveWorkflows(scopeId, workflowIds, fromFolder, toFolder),
        [scopeId],
    );

    const addFolder = useCallback((parentId: string | null, folder: TreeNode) => storeAddFolder(scopeId, parentId, folder), [scopeId]);
    const removeFolder = useCallback((folderId: string) => storeRemoveFolder(scopeId, folderId), [scopeId]);
    const updateFolder = useCallback((folderId: string, updates: Partial<TreeNode>) => storeUpdateFolder(scopeId, folderId, updates), [scopeId]);
    const moveFolders = useCallback((folderIds: string[], toParentId: string | null) => storeMoveFolders(scopeId, folderIds, toParentId), [scopeId]);

    const removeSharedWorkflow = useCallback((workflowId: string) => storeRemoveSharedWorkflow(workflowId), []);
    const removeSharedFolder = useCallback((folderId: string) => storeRemoveSharedFolder(folderId), []);

    // Rollback: capture the current scope + shared before an optimistic mutation,
    // restore on RPC error. Replaces the old exported raw setters.
    const captureRollback = useCallback(() => {
        const snapshot = snapshotScope(scopeId);
        return () => restoreSnapshot(snapshot);
    }, [scopeId]);

    return {
        // State
        folderTree,
        workflowsByFolder,
        sharedWorkflows,
        sharedFolders,
        loadingTree: !slice.foldersLoaded,
        loadingWorkflows,
        // root + every own folder's workflows loaded (drives the search skeleton)
        allWorkflowsLoaded,
        hiddenSharedCount: slice.hiddenSharedCount,
        subscriptionTier: slice.tier,

        // Rollback
        captureRollback,
        clearRemovalTombstone,

        // Fetch
        refreshTree,
        refreshSharedWorkflows,
        fetchWorkflows,
        loadAllWorkflows,

        // Workflow mutations
        addWorkflow,
        removeWorkflow,
        removeWorkflowGlobal,
        updateWorkflow,
        moveWorkflows,
        removeSharedWorkflow,
        removeSharedFolder,

        // Folder mutations
        addFolder,
        removeFolder,
        updateFolder,
        moveFolders,

        // Derived
        getSubfolders,
        getWorkflows,
        getAllWorkflows,
        getFolderPath,
        findFolder,
        getAllFolders,
    };
}
