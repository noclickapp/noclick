// Reusable hook for making workflows draggable
// Used in both sidebar tree and grid view
// VS Code-style: click to select/open, drag to move (with distance threshold in DndContext)

import { useDraggable } from '@dnd-kit/core';

interface UseDraggableWorkflowOptions {
    workflowId: string;
    workflowName: string;
    sourceFolderId?: string | null;
    source: 'grid' | 'sidebar'; // Source of the drag to ensure unique IDs and prevent cross-component drag styling
}

export function useDraggableWorkflow({ workflowId, workflowName, sourceFolderId, source }: UseDraggableWorkflowOptions) {
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `workflow-${source}-${workflowId}`, // Unique ID per source prevents both grid and sidebar from showing drag state
        data: {
            type: 'workflow',
            workflowId,
            workflowName,
            sourceFolderId,
            source, // Include source in data for potential future use
        },
    });

    return {
        attributes,
        listeners,
        setNodeRef,
        isDragging,
    };
}
