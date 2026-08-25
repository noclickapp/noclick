/**
 * Shared utility hook for detecting manually moved nodes in the workflow.
 * Compares actual node positions with their ideal auto-layout positions to determine
 * which nodes have been intentionally positioned by users. This is used to preserve the
 * positions of manually moved nodes during workflow animation.
 */
import { useCallback } from 'react';
import { Node, Edge } from '@xyflow/react';
import { useLayoutCalculation } from './useLayoutCalculation';

export interface LayoutConfig {
  direction: 'TB' | 'BT' | 'LR' | 'RL';
  nodeSpacing: { x: number; y: number };
  levelSpacing: number;
}

export const useManuallyMovedNodes = () => {
  const { calculateLayout } = useLayoutCalculation();

  /**
   * Detects which nodes have been manually moved by comparing their current positions
   * with their ideal auto-layout positions. Returns a Set of node IDs.
   */
  const detectManuallyMovedNodes = useCallback((
    nodes: Node[], 
    edges: Edge[], 
    config: LayoutConfig
  ): Set<string> => {
    if (nodes.length === 0) return new Set();

    let idealNodes: Node[];
    try {
      idealNodes = calculateLayout(nodes, edges, config);
    } catch (error) {
      console.warn('Failed to calculate ideal layout for comparison:', error);
      return new Set(); // If layout fails, assume no nodes are manually moved
    }

    const manuallyMovedIds = new Set<string>();
    
    // Compare actual positions with ideal positions
    nodes.forEach(node => {
      const idealNode = idealNodes.find(n => n.id === node.id);
      if (!idealNode) return;
      
      const dx = Math.abs(node.position.x - idealNode.position.x);
      const dy = Math.abs(node.position.y - idealNode.position.y);
      
      // Use 5% of node spacing as threshold to account for minor adjustments
      const threshold = config.nodeSpacing.x * 0.05; // 10px for 200px spacing
      
      if (dx > threshold || dy > threshold) {
        manuallyMovedIds.add(node.id);
      }
    });

    return manuallyMovedIds;
  }, [calculateLayout]);

  return { detectManuallyMovedNodes };
};