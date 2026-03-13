// Reusable hook for making folders draggable in both sidebar and grid views.
// Mirrors useDraggableWorkflow but with type 'folder' and folder-specific data.

import { useDraggable } from '@dnd-kit/core';

interface UseDraggableFolderOptions {
    folderId: string;
    folderName: string;
    parentFolderId?: string | null;
    /** Materialized path of the folder (e.g. "/uuid1/uuid2/") for circular nesting prevention */
    folderPath?: string;
    source: 'grid' | 'sidebar';
}

export function useDraggableFolder({ folderId, folderName, parentFolderId, folderPath, source }: UseDraggableFolderOptions) {
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `folder-drag-${source}-${folderId}`,
        data: {
            type: 'folder',
            folderId,
            folderName,
            parentFolderId,
            folderPath,
            source,
        },
    });

    return {
        attributes,
        listeners,
        setNodeRef,
        isDragging,
    };
}
