/**
 * useLayoutCalculation - Shared layout calculation logic extracted from useAutoLayout
 * Provides the core d3-hierarchy layout calculation that can be used by both
 * Auto Layout button and workflow animation for consistent positioning.
 */
import { useCallback } from 'react';
import { Node, Edge } from '@xyflow/react';
import { stratify, tree } from 'd3-hierarchy';

export interface LayoutConfig {
  direction: 'TB' | 'BT' | 'LR' | 'RL';
  nodeSpacing: { x: number; y: number };
  levelSpacing: number;
}

// Virtual node prefix for iteration done handles
const ITERATION_DONE_VIRTUAL_PREFIX = '#iteration-done-';

const DEFAULT_CONFIG: LayoutConfig = {
  direction: 'LR',
  nodeSpacing: { x: 200, y: 250 },
  levelSpacing: 120
};

// Constants
const VIRTUAL_ROOT_ID = '#virtual-root';
const DEFAULT_NODE_WIDTH = 240;
const DEFAULT_NODE_HEIGHT = 200;
const BASE_OFFSET_X = 300;
const BASE_OFFSET_Y = 200;

// Enable debug logging
const DEBUG = false;

interface HierarchyNode extends Node {
  parentId?: string;
}

export const useLayoutCalculation = () => {
  /**
   * Calculate layout positions for nodes using d3-hierarchy
   * This is the core logic shared between Auto Layout and workflow animation
   */
  const calculateLayout = useCallback((
    nodes: Node[],
    edges: Edge[],
    config: LayoutConfig = DEFAULT_CONFIG
  ): Node[] => {
    if (nodes.length === 0) {
      return [];
    }

    // Identify iteration nodes for special layout handling
    const iterationNodeIds = new Set(
      nodes.filter(n => n.type === 'iteration').map(n => n.id)
    );

    // Find edges from iteration nodes with 'done' handle
    // These need special treatment to appear after the loop body
    const doneEdges = edges.filter(
      e => iterationNodeIds.has(e.source) && e.sourceHandle === 'done'
    );
    const doneTargetIds = new Set(doneEdges.map(e => e.target));

    // Find edges from iteration nodes with 'loop' handle (or no handle for backwards compat)
    // These identify body nodes that execute per-item
    const loopEdges = edges.filter(
      e => iterationNodeIds.has(e.source) && e.sourceHandle !== 'done'
    );
    const loopBodyNodeIds = new Set(loopEdges.map(e => e.target));

    // Identify loop-back edges: edges FROM body nodes BACK TO iteration nodes
    // These create cycles and should be excluded from parent determination
    const loopBackEdges = new Set(
      edges
        .filter(e => loopBodyNodeIds.has(e.source) && iterationNodeIds.has(e.target))
        .map(e => `${e.source}->${e.target}`)
    );

    if (DEBUG && loopBackEdges.size > 0) {
      console.log(`[LayoutCalculation] Found ${loopBackEdges.size} loop-back edges:`,
        Array.from(loopBackEdges));
    }

    // Helper function to get incoming edges for a given node
    // Excludes loop-back edges to prevent cycles in the hierarchy
    const getIncomingEdges = (nodeId: string): Edge[] => {
      return edges.filter(edge => {
        if (edge.target !== nodeId) return false;
        // Exclude loop-back edges (body node -> iteration node)
        const edgeKey = `${edge.source}->${edge.target}`;
        if (loopBackEdges.has(edgeKey)) return false;
        return true;
      });
    };

    if (DEBUG && doneEdges.length > 0) {
      console.log(`[LayoutCalculation] Found ${doneEdges.length} iteration 'done' edges:`,
        doneEdges.map(e => `${e.source}->${e.target}`));
    }

    if (DEBUG) {
      console.log(`[LayoutCalculation] Calculating layout for ${nodes.length} nodes and ${edges.length} edges`);
      console.log(`[LayoutCalculation] Edges: ${edges.map(e => `${e.source}->${e.target}`).join(', ')}`);
      nodes.forEach(node => {
        console.log(`[LayoutCalculation] Input node ${node.id}: pos(${Math.round(node.position.x)}, ${Math.round(node.position.y)}) size(${node.width || 'default'}x${node.height || 'default'})`);
      });
    }

    // Create a map for quick node lookup
    const nodeMap = new Map<string, Node>();
    nodes.forEach(node => nodeMap.set(node.id, node));

    // Prepare nodes with parent relationships for d3-hierarchy
    // and calculate max dimensions in a single pass
    let maxWidth = 0;
    let maxHeight = 0;

    const hierarchyNodes: HierarchyNode[] = nodes.map(node => {
      const incomingEdges = getIncomingEdges(node.id);

      // Determine parent ID based on incoming edges
      let parentId = VIRTUAL_ROOT_ID;
      if (incomingEdges.length > 0) {
        // Check if this node is connected via a 'done' handle from an iteration node
        const doneEdge = incomingEdges.find(
          e => iterationNodeIds.has(e.source) && e.sourceHandle === 'done'
        );

        if (doneEdge) {
          // For 'done' targets, parent is a virtual intermediate node
          // This pushes them one level deeper than the loop body
          parentId = `${ITERATION_DONE_VIRTUAL_PREFIX}${doneEdge.source}`;
        } else {
          // Normal case: use the first incoming edge's source
          parentId = incomingEdges[0].source;
        }
      }

      if (DEBUG) {
        if (incomingEdges.length > 1) {
          console.log(`[LayoutCalculation] Node ${node.id} has ${incomingEdges.length} parents: [${incomingEdges.map(e => e.source).join(', ')}], using: ${parentId}`);
        } else if (incomingEdges.length === 1) {
          console.log(`[LayoutCalculation] Node ${node.id} parent: ${parentId}`);
        } else {
          console.log(`[LayoutCalculation] Node ${node.id} is root (no parents)`);
        }
      }

      // Use measured dimensions if available, otherwise defaults
      const width = node.width || DEFAULT_NODE_WIDTH;
      const height = node.height || DEFAULT_NODE_HEIGHT;

      // Track max dimensions
      maxWidth = Math.max(maxWidth, width);
      maxHeight = Math.max(maxHeight, height);

      return {
        ...node,
        parentId,
        width,
        height
      };
    });

    // Add virtual intermediate nodes for iteration 'done' edges
    // These create an extra level between the iteration node and done targets
    for (const iterationId of Array.from(iterationNodeIds)) {
      const hasDoneEdge = doneEdges.some(e => e.source === iterationId);
      if (hasDoneEdge) {
        const virtualDoneNode: HierarchyNode = {
          id: `${ITERATION_DONE_VIRTUAL_PREFIX}${iterationId}`,
          type: 'virtual',
          position: { x: 0, y: 0 },
          data: {},
          parentId: iterationId, // Virtual node is child of iteration
          width: 0,
          height: 0
        };
        hierarchyNodes.push(virtualDoneNode);

        if (DEBUG) {
          console.log(`[LayoutCalculation] Added virtual done node for iteration ${iterationId}`);
        }
      }
    }

    // Add virtual root node
    const virtualRoot: HierarchyNode = {
      id: VIRTUAL_ROOT_ID,
      type: 'virtual',
      position: { x: 0, y: 0 },
      data: {},
      width: 0,
      height: 0
    };
    hierarchyNodes.unshift(virtualRoot);

    // Create hierarchy using stratify
    let root;
    try {
      const stratifyFn = stratify<HierarchyNode>()
        .id(d => d.id)
        .parentId(d => d.parentId);

      root = stratifyFn(hierarchyNodes);
    } catch (error) {
      console.error('[LayoutCalculation] Error creating hierarchy:', error);
      console.error('[LayoutCalculation] This may indicate circular dependencies or invalid parent references');
      return nodes; // Return original nodes if hierarchy fails
    }

    // Sort children of iteration nodes so that:
    // - "done" connected nodes (via virtual intermediate) come first (positioned at top)
    // - "loop" connected nodes come last (positioned at bottom)
    // This prevents edge crossings since done handle is at top (30%) and loop handle is at bottom (70%)
    root.each(node => {
      if (node.children && node.children.length > 1 && iterationNodeIds.has(node.data.id)) {
        node.children.sort((a, b) => {
          // Virtual done nodes should come first (top position)
          const aIsVirtualDone = a.data.id.startsWith(ITERATION_DONE_VIRTUAL_PREFIX);
          const bIsVirtualDone = b.data.id.startsWith(ITERATION_DONE_VIRTUAL_PREFIX);

          if (aIsVirtualDone && !bIsVirtualDone) return -1; // a comes before b (top)
          if (!aIsVirtualDone && bIsVirtualDone) return 1;  // a comes after b (bottom)
          return 0;
        });

        if (DEBUG) {
          console.log(`[LayoutCalculation] Sorted children of ${node.data.id}:`,
            node.children.map(c => c.data.id));
        }
      }
    });

    // Determine layout properties based on direction
    const isHorizontal = config.direction === 'LR' || config.direction === 'RL';

    // Configure tree layout
    const treeLayout = tree<HierarchyNode>()
      .nodeSize(isHorizontal 
        ? [maxHeight + config.nodeSpacing.y, maxWidth + config.nodeSpacing.x]
        : [maxWidth + config.nodeSpacing.x, maxHeight + config.nodeSpacing.y]
      )
      .separation(() => 1);

    // Apply layout
    treeLayout(root);

    // Extract positions and apply to nodes
    const layoutedNodes = nodes.map(node => {
      const hierarchyNode = root.descendants().find(n => n.data.id === node.id);
      
      if (!hierarchyNode) {
        if (DEBUG) {
          console.warn(`[LayoutCalculation] No hierarchy node found for ${node.id}`);
        }
        return node;
      }

      // d3 assigns both coordinates when treeLayout(root) runs above; retain a
      // defensive zero fallback for malformed/custom hierarchy nodes.
      let x = hierarchyNode.x ?? 0;
      let y = hierarchyNode.y ?? 0;

      // Apply direction transformations
      if (isHorizontal) {
        // Swap x and y for horizontal layouts
        [x, y] = [y, x];
      }

      // Apply direction-specific transformations
      switch (config.direction) {
        case 'BT':
          y = -y;
          break;
        case 'RL':
          x = -x;
          break;
      }

      // Convert from center-based to top-left coordinates
      const nodeWidth = node.width || DEFAULT_NODE_WIDTH;
      const nodeHeight = node.height || DEFAULT_NODE_HEIGHT;
      x = x - nodeWidth / 2 + BASE_OFFSET_X;
      y = y - nodeHeight / 2 + BASE_OFFSET_Y;

      return {
        ...node,
        position: { x, y }
      };
    });

    if (DEBUG) {
      console.log('[LayoutCalculation] Layout complete');
      layoutedNodes.forEach(node => {
        console.log(`[LayoutCalculation] Output node ${node.id}: pos(${Math.round(node.position.x)}, ${Math.round(node.position.y)})`);
      });
    }
    return layoutedNodes;
  }, []);

  return {
    calculateLayout
  };
};
