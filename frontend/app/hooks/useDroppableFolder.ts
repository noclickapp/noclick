// Reusable hook for making folders accept workflow drops
// Used in sidebar tree for folder drop zones

import { useDroppable } from '@dnd-kit/core';

interface UseDroppableFolderOptions {
    folderId: string | null; // null = root folder
}

export function useDroppableFolder({ folderId }: UseDroppableFolderOptions) {
    const { isOver, setNodeRef, active } = useDroppable({
        id: folderId ? `folder-${folderId}` : 'folder-root',
        data: {
            type: 'folder',
            folderId,
        },
    });

    // Only show drop feedback if dragging a workflow
    const isDraggingWorkflow = active?.data?.current?.type === 'workflow';
    const showDropFeedback = isOver && isDraggingWorkflow;

    return {
        isOver: showDropFeedback,
        setNodeRef,
        isDraggingWorkflow,
    };
}
