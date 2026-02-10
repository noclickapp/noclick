// Reusable hook for making workflows draggable
// Used in both sidebar tree and grid view
// VS Code-style: click to select/open, drag to move (with distance threshold in DndContext)

import { useDraggable } from '@dnd-kit/core';

interface UseDraggableWorkflowOptions {
    workflowId: string;
    workflowName: string;
    sourceFolderId?: string | null;
}

export function useDraggableWorkflow({ workflowId, workflowName, sourceFolderId }: UseDraggableWorkflowOptions) {
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `workflow-${workflowId}`,
        data: {
            type: 'workflow',
            workflowId,
            workflowName,
            sourceFolderId,
        },
    });

    return {
        attributes,
        listeners,
        setNodeRef,
        isDragging,
    };
}
