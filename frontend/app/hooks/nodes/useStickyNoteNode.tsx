/**
 * Hook for managing sticky note node behavior including z-index management and content editing.
 * Encapsulates all sticky note-specific logic to keep FlowCanvas clean.
 */
import React, { useCallback, useMemo } from 'react';
import { Node } from '@xyflow/react';
import { useNodeZIndex } from '../useNodeZIndex';
import StickyNote from '~/components/workflow/nodes/StickyNote';
import { updateNodeInList } from '~/lib/applyNodeUpdate';

interface UseStickyNoteNodeProps {
  setNodes: (updater: (nodes: Node[]) => Node[]) => void;
}

export function useStickyNoteNode({ setNodes }: UseStickyNoteNodeProps) {
  // Configure z-index management for sticky notes and normal nodes
  // Sticky notes use area-based stacking (larger = further back)
  // Normal nodes always appear above sticky notes via higher baseZIndex
  // Memoize groups config to prevent infinite loop
  const zIndexGroups = useMemo(() => [
    {
      // Sticky notes: baseZIndex 0, so they get z-index 1-999
      filter: (node: Node) => node.type === 'stickyNote',
      calculatePriority: (node: Node) => {
        // Editing notes should be on top of other sticky notes (lowest priority = highest z-index within group)
        if (node.data?.isEditing) {
          return -Infinity;
        }
        // Otherwise area-based: larger notes stay in back
        const width = Number(node.width || node.style?.width || 200);
        const height = Number(node.height || node.style?.height || 150);
        return width * height;
      },
      order: 'desc' as const, // larger area/priority = lower z-index (further back)
      baseZIndex: 0,
    },
    {
      // Normal nodes: baseZIndex 1000, so they always appear above sticky notes
      filter: (node: Node) => node.type !== 'stickyNote',
      calculatePriority: () => 0, // All normal nodes have same priority (no special ordering)
      order: 'asc' as const,
      baseZIndex: 1000,
    },
  ], []);

  const { recalculateZIndex } = useNodeZIndex({
    groups: zIndexGroups,
  });

  // Callback to handle sticky note content changes
  const handleStickyNoteContentChange = useCallback((nodeId: string, newContent: string) => {
    const nodesSetter = setNodes;
    nodesSetter(nodes => updateNodeInList(nodes, nodeId, { content: newContent }));
  }, [setNodes]);

  // Callback to handle sticky note editing state changes (for z-index management)
  const handleStickyNoteEditingChange = useCallback((nodeId: string, isEditing: boolean) => {
    const nodesSetter = setNodes;
    nodesSetter((nodes) => {
      // First update the isEditing flag
      const updatedNodes = updateNodeInList(nodes, nodeId, { extras: { isEditing } });
      // Then recalculate z-index so editing note comes to front
      return recalculateZIndex(updatedNodes);
    });
  }, [setNodes, recalculateZIndex]);

  // Callback to handle sticky note color changes
  const handleStickyNoteColorChange = useCallback((nodeId: string, newColor: number) => {
    const nodesSetter = setNodes;
    nodesSetter(nodes => updateNodeInList(nodes, nodeId, { color: newColor }));
  }, [setNodes]);

  // Callback to handle sticky note deletion
  const handleStickyNoteDelete = useCallback((nodeId: string) => {
    const nodesSetter = setNodes;
    nodesSetter((nodes) => nodes.filter((node) => node.id !== nodeId));
  }, [setNodes]);

  // Create sticky note renderer with callbacks
  const stickyNoteRenderer = useCallback((props: any) => (
    <StickyNote {...props} data={{
      ...props.data,
      onContentChange: (newContent: string) => handleStickyNoteContentChange(props.id, newContent),
      onEditingChange: (isEditing: boolean) => handleStickyNoteEditingChange(props.id, isEditing),
      onColorChange: (newColor: number) => handleStickyNoteColorChange(props.id, newColor),
      onDelete: () => handleStickyNoteDelete(props.id)
    }} />
  ), [handleStickyNoteContentChange, handleStickyNoteEditingChange, handleStickyNoteColorChange, handleStickyNoteDelete]);

  return {
    stickyNoteRenderer,
    recalculateZIndex,
  };
}
