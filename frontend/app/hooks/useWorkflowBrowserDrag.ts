import { useCallback, useRef, useState } from 'react';
import { DragEndEvent, DragStartEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { FolderUpdateRequest } from '~/types/socket-events.generated';
import type { WorkflowApp, FolderInfoLocal, useWorkflowBrowserData } from '~/hooks/useWorkflowBrowserData';
import type { useGridSelection } from '~/hooks/useGridSelection';

type FolderInfo = FolderInfoLocal;
type Store = ReturnType<typeof useWorkflowBrowserData>;
type Selection = ReturnType<typeof useGridSelection>;

interface SidebarSelectionApi {
    getSelectedIds: () => string[];
    clearSelection: () => void;
}

interface UseWorkflowBrowserDragParams {
    store: Store;
    selection: Selection;
    currentFolders: FolderInfo[];
    workflows: WorkflowApp[];
}

export function useWorkflowBrowserDrag({
    store,
    selection,
    currentFolders,
    workflows,
}: UseWorkflowBrowserDragParams) {
    const [activeWorkflow, setActiveWorkflow] = useState<WorkflowApp | null>(null);
    const [activeFolder, setActiveFolder] = useState<FolderInfo | null>(null);
    // 'list' is the compact row layout of the main browser — it shares the grid's
    // `selection` for multi-drag but renders a compact drag overlay like 'sidebar'.
    const [dragSource, setDragSource] = useState<'grid' | 'sidebar' | 'list' | null>(null);
    // Track IDs being dragged so ALL selected cards gray out, not just the one under the pointer
    const [draggingIds, setDraggingIds] = useState<Set<string>>(new Set());

    const draggedWorkflowIdsRef = useRef<string[]>([]);
    const draggedFolderIdsRef = useRef<string[]>([]);
    // Ref so the DragOverlay reads correct dimensions on the same render as drag start
    const dragPreviewDimensionsRef = useRef<{ width: number; height: number }>({ width: 280, height: 280 });
    // Sidebar registers its multi-select API here so cross-surface drags can read/clear it
    const sidebarSelectionRef = useRef<SidebarSelectionApi | null>(null);

    // Configure drag sensors with distance activation (VS Code-style: click vs drag)
    // Requires 8px movement before drag starts, allowing clicks to work normally
    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: {
                distance: 8, // 8px movement required to start drag
            },
        })
    );

    const handleDragStart = useCallback(
        (event: DragStartEvent) => {
            const dragType = event.active.data.current?.type;
            const source = event.active.data.current?.source as 'grid' | 'sidebar' | 'list';
            // The grid and list layouts share the same `selection` store, so
            // multi-drag detection treats them identically.
            const usesGridSelection = source === 'grid' || source === 'list';

            // Handle folder drag start
            if (dragType === 'folder') {
                const folderId = event.active.data.current?.folderId;
                const folderName = event.active.data.current?.folderName;
                if (!folderId) return;

                // Determine which folders are being dragged (multi-select aware)
                if (usesGridSelection && selection.isSelected(folderId) && selection.selectedIds.size > 1) {
                    // Dragging a selected folder from grid/list — include all selected
                    // OWNED folders. Not-owned (shared) folders can be selected in
                    // "Owned by anyone" but moving them would be rejected server-side.
                    const selectedFolderIds = currentFolders
                        .filter((f) => selection.isSelected(f.id) && f.is_owner !== false)
                        .map((f) => f.id);
                    draggedFolderIdsRef.current = selectedFolderIds;
                    setDraggingIds(new Set(selection.getSelectedArray()));
                } else if (source === 'sidebar' && sidebarSelectionRef.current) {
                    const sidebarIds = sidebarSelectionRef.current.getSelectedIds();
                    if (sidebarIds.includes(folderId) && sidebarIds.length > 1) {
                        draggedFolderIdsRef.current = sidebarIds;
                        setDraggingIds(new Set(sidebarIds));
                    } else {
                        draggedFolderIdsRef.current = [folderId];
                        setDraggingIds(new Set([folderId]));
                    }
                } else {
                    draggedFolderIdsRef.current = [folderId];
                    setDraggingIds(new Set([folderId]));
                }

                setDragSource(source || 'grid');
                const folder = currentFolders.find((f) => f.id === folderId);
                setActiveFolder(
                    folder ?? { id: folderId, name: folderName || 'Folder', description: '', workflow_count: 0 }
                );

                // Capture card dimensions for grid drag overlay
                if (source === 'grid') {
                    const el =
                        (event.active as any).node?.current ?? document.querySelector(`[data-folder-card]`);
                    if (el) {
                        const rect = el.getBoundingClientRect();
                        dragPreviewDimensionsRef.current = { width: rect.width, height: rect.height };
                    }
                }
                return;
            }

            const workflowId = event.active.data.current?.workflowId;
            const workflowName = event.active.data.current?.workflowName;

            if (!workflowId) return;

            // Determine which workflows are being dragged (check multi-select from grid/list or sidebar)
            if (usesGridSelection && selection.isSelected(workflowId) && selection.selectedIds.size > 1) {
                // The grid/list selection can mix folders + workflows (the list
                // interleaves them); restrict the workflow move to OWNED workflow
                // IDs so folder IDs never get sent as workflow_id and not-owned
                // (shared) flows — selectable in "Owned by anyone" — aren't dragged
                // into a doomed move that snaps back.
                const workflowIdSet = new Set(
                    workflows.filter((w) => w.is_owner !== false).map((w) => w.id)
                );
                const ids = selection.getSelectedArray().filter((id) => workflowIdSet.has(id));
                draggedWorkflowIdsRef.current = ids.length ? ids : [workflowId];
                setDraggingIds(new Set(draggedWorkflowIdsRef.current));
            } else if (source === 'sidebar' && sidebarSelectionRef.current) {
                const sidebarIds = sidebarSelectionRef.current.getSelectedIds();
                if (sidebarIds.includes(workflowId) && sidebarIds.length > 1) {
                    draggedWorkflowIdsRef.current = sidebarIds;
                    setDraggingIds(new Set(sidebarIds));
                } else {
                    draggedWorkflowIdsRef.current = [workflowId];
                    setDraggingIds(new Set([workflowId]));
                }
            } else {
                draggedWorkflowIdsRef.current = [workflowId];
                setDraggingIds(new Set([workflowId]));
            }

            // Use the actual source from drag data (not inferred from sourceFolderId)
            setDragSource(source || 'grid');

            // Capture actual card dimensions for drag preview to match exact size.
            // Measure from the active element's rect, with DOM query fallback.
            if (source === 'grid') {
                const el = (event.active as any).node?.current ?? document.querySelector(`[data-workflow-card]`);
                if (el) {
                    const rect = el.getBoundingClientRect();
                    dragPreviewDimensionsRef.current = { width: rect.width, height: rect.height };
                }
            }

            // Try to find workflow in main list
            const workflow = workflows.find((w) => w.id === workflowId);
            if (workflow) {
                setActiveWorkflow(workflow);
            } else if (workflowName) {
                // Workflow is from sidebar - create temporary object for drag overlay
                setActiveWorkflow({
                    id: workflowId,
                    name: workflowName,
                    description: '',
                    created_at: '',
                    updated_at: '',
                    is_owner: true,
                    user_permission: 'owner',
                });
            }
        },
        [workflows, selection, currentFolders]
    );

    const handleDragEnd = useCallback(
        (event: DragEndEvent) => {
            const { active, over } = event;
            const dragType = active.data.current?.type;

            // Clear all drag state
            setActiveWorkflow(null);
            setActiveFolder(null);
            setDragSource(null);
            setDraggingIds(new Set());

            // Handle folder drop
            if (dragType === 'folder') {
                const draggedIds = draggedFolderIdsRef.current;
                draggedFolderIdsRef.current = [];
                if (!over || draggedIds.length === 0) return;

                const targetFolderId = over.data.current?.folderId ?? null;
                const targetPath = over.data.current?.folderPath as string | undefined;

                // Filter out invalid moves (self-drop, same parent, circular)
                const validIds = draggedIds.filter((id) => {
                    if (id === targetFolderId) return false;
                    if (targetFolderId && targetPath?.includes(`/${id}/`)) return false;
                    const folder = currentFolders.find((f) => f.id === id);
                    if (folder && (folder.parent_folder_id ?? null) === targetFolderId) return false;
                    return true;
                });
                if (validIds.length === 0) return;

                // Capture scope for rollback before the optimistic move
                const rollback = store.captureRollback();

                // Optimistic: move folders in unified store
                store.moveFolders(validIds, targetFolderId);

                // Clear multi-select after drop
                selection.clearSelection();

                // Move each folder via backend
                let completedCount = 0;
                const onComplete = () => {
                    completedCount++;
                    if (completedCount < validIds.length) return;
                    store.refreshTree();
                };

                validIds.forEach((folderId) => {
                    sendEventWithCallback(
                        FolderUpdateRequest.create({
                            folder_id: folderId,
                            parent_folder_id: targetFolderId,
                        }),
                        (response) => {
                            if (!response.success) {
                                console.error(`Failed to move folder ${folderId}:`, response.message);
                                rollback();
                            }
                            onComplete();
                        }
                    );
                });
                return;
            }

            // Handle workflow drop
            const draggedIds = draggedWorkflowIdsRef.current;
            draggedWorkflowIdsRef.current = [];

            if (!over || draggedIds.length === 0) return;

            const sourceFolderId = active.data.current?.sourceFolderId;
            const targetFolderId = over.data.current?.folderId || null;

            // Don't do anything if dropped in same folder
            if (sourceFolderId === targetFolderId) return;

            // Capture scope for rollback before the optimistic move
            const rollback = store.captureRollback();

            // Optimistic: move workflows in unified store (updates grid + sidebar + folder counts)
            store.moveWorkflows(draggedIds, sourceFolderId ?? null, targetFolderId);

            // Clear multi-select after drop (both grid and sidebar)
            selection.clearSelection();
            sidebarSelectionRef.current?.clearSelection();

            // Move each workflow to folder via backend
            let completedCount = 0;
            const onComplete = () => {
                completedCount++;
                if (completedCount < draggedIds.length) return;
                // Refresh tree for authoritative folder counts
                store.refreshTree();
            };

            draggedIds.forEach((id) => {
                sendEventWithCallback(
                    {
                        event_name: 'workflow_folder:move_workflow' as const,
                        workflow_id: id,
                        folder_id: targetFolderId,
                    },
                    (response) => {
                        if (!response.success) {
                            console.error(`Failed to move workflow ${id}:`, response.message);
                            rollback();
                        }
                        onComplete();
                    }
                );
            });
        },
        [store, selection, currentFolders]
    );

    return {
        sensors,
        activeWorkflow,
        activeFolder,
        dragSource,
        draggingIds,
        draggedWorkflowIdsRef,
        draggedFolderIdsRef,
        dragPreviewDimensionsRef,
        sidebarSelectionRef,
        handleDragStart,
        handleDragEnd,
    };
}
