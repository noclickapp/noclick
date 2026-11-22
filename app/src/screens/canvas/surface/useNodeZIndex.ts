/**
 * Generic hook for managing z-index stacking of nodes based on custom criteria.
 * Allows different node types to have different stacking rules (e.g., area-based for sticky notes).
 * Supports baseZIndex per group to ensure certain node types always appear above/below others.
 */
import { useCallback } from 'react';
import { Node } from '@xyflow/react';

interface NodeGroup {
  /** Filter function to select which nodes this rule applies to */
  filter: (node: Node) => boolean;
  /** Calculate a priority value for sorting (e.g., area, custom score, etc.) */
  calculatePriority: (node: Node) => number;
  /** Sort order: 'desc' means higher priority = lower z-index (further back) */
  order: 'asc' | 'desc';
  /** Base z-index for this group (default: 0). Nodes in this group get baseZIndex + position */
  baseZIndex?: number;
}

interface UseNodeZIndexOptions {
  /** Groups of nodes with their stacking rules */
  groups: NodeGroup[];
}

/**
 * Hook that manages z-index for nodes based on configurable groups and criteria.
 * Call recalculateZIndex in your onNodesChange handler to maintain z-index on every update.
 *
 * @example
 * ```tsx
 * const { recalculateZIndex } = useNodeZIndex({
 *   groups: [{
 *     filter: (n) => n.type === 'stickyNote',
 *     calculatePriority: (n) => (n.width || 200) * (n.height || 150), // area
 *     order: 'desc', // larger area = further back
 *   }]
 * });
 *
 * const onNodesChange = useCallback((changes) => {
 *   setNodes((nds) => {
 *     let updated = applyNodeChanges(changes, nds);
 *     updated = recalculateZIndex(updated);
 *     return updated;
 *   });
 * }, [recalculateZIndex]);
 * ```
 */
export function useNodeZIndex({ groups }: UseNodeZIndexOptions) {
  /**
   * Recalculates z-index for all nodes based on configured groups.
   * Only updates nodes if z-index has actually changed to prevent unnecessary re-renders.
   */
  const recalculateZIndex = useCallback((nodesToProcess: Node[]): Node[] => {
    if (groups.length === 0) return nodesToProcess;

    // Separate nodes into groups and ungrouped
    const groupedNodes: Node[][] = [];
    const ungroupedNodes: Node[] = [];

    // First pass: identify which group each node belongs to (if any)
    nodesToProcess.forEach(node => {
      let matched = false;
      groups.forEach((group, groupIndex) => {
        if (group.filter(node)) {
          if (!groupedNodes[groupIndex]) {
            groupedNodes[groupIndex] = [];
          }
          groupedNodes[groupIndex].push(node);
          matched = true;
        }
      });
      if (!matched) {
        ungroupedNodes.push(node);
      }
    });

    // Process each group: calculate priority, sort, assign z-index
    const processedGroups: Node[][] = groupedNodes.map((groupNodes, groupIndex) => {
      if (!groupNodes || groupNodes.length === 0) return [];

      const group = groups[groupIndex];

      // Calculate priority for each node in the group
      const withPriority = groupNodes.map(node => ({
        node,
        priority: group.calculatePriority(node),
      }));

      // Sort by priority
      const sorted = withPriority.sort((a, b) => {
        if (group.order === 'desc') {
          return b.priority - a.priority; // Highest priority first
        } else {
          return a.priority - b.priority; // Lowest priority first
        }
      });

      // Assign z-index: first in sorted array gets lowest z-index
      // Use baseZIndex to offset the group (allows layering groups above each other)
      // Only create new object if z-index changed to prevent unnecessary re-renders
      const baseZIndex = group.baseZIndex ?? 0;
      return sorted.map(({ node }, index) => {
        const newZIndex = baseZIndex + index + 1;
        const currentZIndex = node.style?.zIndex;

        if (currentZIndex === newZIndex) {
          return node; // No change needed
        }

        return {
          ...node,
          style: { ...node.style, zIndex: newZIndex },
        };
      });
    });

    // Flatten and combine all nodes
    return [...ungroupedNodes, ...processedGroups.flat()];
  }, [groups]);

  return {
    /** Function to recalculate z-index - use this in onNodesChange */
    recalculateZIndex,
  };
}
