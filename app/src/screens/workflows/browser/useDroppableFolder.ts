// Reusable hook for making elements accept workflow and folder drops into a folder.
// Used in sidebar tree for folder drop zones and child rows that proxy to their parent folder.

import { useDroppable } from '@dnd-kit/core';

interface UseDroppableFolderOptions {
    folderId: string | null; // null = root folder
    // Optional unique suffix to prevent ID collisions when multiple elements target the same folder
    idSuffix?: string;
    /** Materialized path of the target folder (e.g. "/uuid1/uuid2/") for circular nesting prevention */
    targetFolderPath?: string;
}

export function useDroppableFolder({ folderId, idSuffix, targetFolderPath }: UseDroppableFolderOptions) {
    const baseId = folderId ? `folder-${folderId}` : 'folder-root';
    const id = idSuffix ? `${baseId}-${idSuffix}` : baseId;

    const { isOver, setNodeRef, active } = useDroppable({
        id,
        data: {
            type: 'folder',
            folderId,
            folderPath: targetFolderPath,
        },
    });

    const dragType = active?.data?.current?.type;
    const isDraggingWorkflow = dragType === 'workflow';
    const isDraggingFolder = dragType === 'folder';

    // Prevent dropping a folder onto itself or into its own descendants (circular nesting)
    const isSelfDrop = isDraggingFolder && active?.data?.current?.folderId === folderId;
    // Block if the target folder is a descendant of the dragged folder (would create a cycle)
    const draggedFolderId = active?.data?.current?.folderId as string | undefined;
    const isDescendantDrop = isDraggingFolder && draggedFolderId != null
        && targetFolderPath != null && targetFolderPath.includes(`/${draggedFolderId}/`);

    const showDropFeedback = isOver && (isDraggingWorkflow || isDraggingFolder) && !isSelfDrop && !isDescendantDrop;

    return {
        isOver: showDropFeedback,
        setNodeRef,
        isDraggingWorkflow,
        isDraggingFolder,
    };
}
