// Reusable hook for making elements accept workflow drops into a folder
// Used in sidebar tree for folder drop zones and child rows that proxy to their parent folder

import { useDroppable } from '@dnd-kit/core';

interface UseDroppableFolderOptions {
    folderId: string | null; // null = root folder
    // Optional unique suffix to prevent ID collisions when multiple elements target the same folder
    idSuffix?: string;
}

export function useDroppableFolder({ folderId, idSuffix }: UseDroppableFolderOptions) {
    const baseId = folderId ? `folder-${folderId}` : 'folder-root';
    const id = idSuffix ? `${baseId}-${idSuffix}` : baseId;

    const { isOver, setNodeRef, active } = useDroppable({
        id,
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
