/**
 * workflowLayout - Utility functions for workflow nodes and edges.
 * Provides layout algorithms for node positioning and consistent edge styling.
 * Can be extended later to integrate with more sophisticated layout libraries like Dagre or ElkJS.
 */
import { Node, Edge } from '@xyflow/react';

// ============================================================================
// Edge Styling - Single source of truth for workflow edge appearance
// ============================================================================

/**
 * Default edge style used throughout the workflow canvas.
 * Use createStyledEdge() to create edges with this styling.
 */
export const DEFAULT_EDGE_STYLE = {
    // Match the rendered edge color (AnimatedWorkflowEdge forces this): soft gray
    // in light, white in dark. Was --foreground, which made hint/next-step edges
    // near-black on the light canvas — darker than real edges.
    stroke: 'hsl(var(--canvas-edge))',
    strokeWidth: 3,
    opacity: 0.8,
    strokeDasharray: '5 5',
} as const;

/**
 * Creates a styled edge with consistent appearance across the workflow.
 * Use this function instead of manually specifying edge styles to ensure consistency.
 * Uses 'animated' type which maps to AnimatedWorkflowEdge (bezier curves).
 */
export function createStyledEdge(params: {
    id?: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
    type?: string;
}): Edge {
    const { id, source, target, sourceHandle, targetHandle, type = 'animated' } = params;
    return {
        id: id || `e_${source}_${target}`,
        source,
        target,
        sourceHandle,
        targetHandle,
        type,
        animated: true,
        style: { ...DEFAULT_EDGE_STYLE },
        data: { isAnimating: false },
    };
}

/**
 * Drop edges duplicating an identical connection (same endpoints + handles).
 * Stale canvas state has produced doubled edges, which render two stacked
 * midpoint chips (hovering one shows its delete button on top of the twin's
 * chip) and double-count dependencies. First occurrence wins.
 */
export function dedupeEdges(edges: Edge[]): Edge[] {
    const seen = new Set<string>();
    return edges.filter((e) => {
        const key = `${e.source}|${e.sourceHandle ?? ''}|${e.target}|${e.targetHandle ?? ''}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

/**
 * Applies default styling to an existing edge or array of edges.
 * Useful when loading edges from backend that may not have styling.
 * Uses 'animated' type which maps to AnimatedWorkflowEdge (bezier curves).
 */
export function applyEdgeStyle(edge: Edge): Edge {
    return {
        ...edge,
        type: edge.type || 'animated',
        animated: true,
        style: { ...DEFAULT_EDGE_STYLE },
        data: { isAnimating: false, ...edge.data },
    };
}

// ============================================================================
// Node Size Estimation
// ============================================================================

/**
 * Estimates node height based on node type.
 * Used by layout algorithm to prevent overlapping nodes of different sizes.
 */
// Exported: WorkflowGraphPreview derives its tile footprints from these so the
// thumbnail can't drift from the layout algorithm's node sizes.
export const NODE_HEIGHT_MAP: Record<string, number> = {
  // Taller nodes - 'agent'
  'agent': 140,
  // Sticky notes can vary, use generous default
  'sticky-note': 150,
  // Form inputs are taller
  'form-input': 120,
};

/**
 * Estimates node width based on node type.
 * Used by layout algorithm to center-align nodes horizontally within layers.
 * Values match actual component dimensions from node definitions.
 */
export const NODE_WIDTH_MAP: Record<string, number> = {
  // AI Agent node is wider (200px vs 90px for automation nodes)
  'agent': 200,
  // Sticky notes can be wider
  'sticky-note': 250,
};

export const DEFAULT_NODE_HEIGHT = 90; // Standard automation node height
export const DEFAULT_NODE_WIDTH = 90; // Standard automation node width

function estimateNodeHeight(node: Node): number {
  const nodeType = node.type || '';
  return NODE_HEIGHT_MAP[nodeType] || DEFAULT_NODE_HEIGHT;
}

function estimateNodeWidth(node: Node): number {
  const nodeType = node.type || '';
  return NODE_WIDTH_MAP[nodeType] || DEFAULT_NODE_WIDTH;
}

// ============================================================================
// Handle Order - Defines vertical order of output handles for multi-output nodes
// ============================================================================

/**
 * Handle order configuration for multi-output node types.
 * Handles listed first appear at the top, handles listed later appear at the bottom.
 * This ensures nodes connected to top handles are positioned above nodes connected to bottom handles.
 *
 * To add a new multi-output node type, add an entry here with handles in top-to-bottom order.
 */
const HANDLE_ORDER: Record<string, string[]> = {
  // Iteration node: "done" handle is at top-right, "loop" handle is at bottom-right
  'iteration': ['done', 'loop'],
  // Add more multi-output node types here as needed
  // 'conditional': ['true', 'false'],
  // 'switch': ['case1', 'case2', 'case3', 'default'],
};

/**
 * Get the vertical sort order for a child node based on the handle it's connected to.
 * Lower values = positioned higher (towards top), higher values = positioned lower (towards bottom).
 * Returns 0 for nodes without sourceHandle or nodes connected to unknown handles.
 */
function getHandleOrder(sourceNodeType: string | undefined, sourceHandle: string | undefined): number {
  if (!sourceNodeType || !sourceHandle) return 0;

  const handleList = HANDLE_ORDER[sourceNodeType];
  if (!handleList) return 0;

  const index = handleList.indexOf(sourceHandle);
  return index >= 0 ? index : 0;
}

// ============================================================================
// Back Edge Detection - Identifies edges that loop back in iteration patterns
// ============================================================================

/**
 * Detects if an edge is a "back edge" in an iteration loop pattern.
 * Back edges go FROM a loop body node BACK TO the iteration node.
 * These should be excluded from layer assignment to prevent cycles.
 *
 * Pattern: iteration --[loop]--> body --> iteration (back edge)
 */
function isBackEdge(edge: Edge, allEdges: Edge[], nodeMap: Map<string, Node>): boolean {
  const targetNode = nodeMap.get(edge.target);
  if (!targetNode) return false;

  // Only iteration nodes can receive back edges
  if (targetNode.type !== 'iteration') return false;

  // Check if the iteration node has a "loop" edge going TO the source of this edge
  // If so, this edge is the return path of the loop and is a back edge
  const hasLoopToSource = allEdges.some(e =>
    e.source === edge.target &&
    e.target === edge.source &&
    e.sourceHandle === 'loop'
  );

  return hasLoopToSource;
}

// ============================================================================
// Layout Options
// ============================================================================

export interface LayoutOptions {
  direction: 'horizontal' | 'vertical';
  spacing: { x: number; y: number };
  startPosition: { x: number; y: number };
}

const DEFAULT_LAYOUT_OPTIONS: LayoutOptions = {
  direction: 'horizontal',
  spacing: { x: 280, y: 40 }, // Base gap between nodes (actual spacing = gap + node height)
  startPosition: { x: 100, y: 200 }
};

/**
 * Left-to-right layout that centers parent nodes relative to their children.
 * Similar to tree layout - positions leaves first, then centers parents.
 * Children are ordered by their source handle position (top handles first, bottom handles last).
 */
export function applySimpleLayout(nodes: Node[], edges: Edge[], options?: Partial<LayoutOptions>): Node[] {
  const opts = { ...DEFAULT_LAYOUT_OPTIONS, ...options };

  if (nodes.length === 0) return nodes;

  // Build graph structure
  const nodeMap = new Map<string, Node>();
  const children = new Map<string, string[]>(); // parent -> children
  const parents = new Map<string, string[]>();  // child -> parents
  const inDegree = new Map<string, number>();
  // Track which handle connects each parent to each child (for ordering by handle position)
  const edgeHandles = new Map<string, string | undefined>(); // "parent->child" -> sourceHandle

  nodes.forEach(node => {
    nodeMap.set(node.id, node);
    children.set(node.id, []);
    parents.set(node.id, []);
    inDegree.set(node.id, 0);
  });

  // Process edges, excluding back edges from layer calculation
  // Back edges are stored separately for handle tracking but don't affect parent/child relationships
  edges.forEach(edge => {
    if (nodeMap.has(edge.source) && nodeMap.has(edge.target)) {
      // Store the sourceHandle for all edges (needed for handle ordering)
      edgeHandles.set(`${edge.source}->${edge.target}`, edge.sourceHandle ?? undefined);

      // Skip back edges for parent/child/inDegree - they create cycles
      if (isBackEdge(edge, edges, nodeMap)) {
        return;
      }

      children.get(edge.source)!.push(edge.target);
      parents.get(edge.target)!.push(edge.source);
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
    }
  });

  // Sort children of each node by handle order (top handles first, bottom handles last)
  children.forEach((childList, parentId) => {
    const parentNode = nodeMap.get(parentId);
    const parentType = parentNode?.type;

    childList.sort((a, b) => {
      const handleA = edgeHandles.get(`${parentId}->${a}`);
      const handleB = edgeHandles.get(`${parentId}->${b}`);
      const orderA = getHandleOrder(parentType, handleA);
      const orderB = getHandleOrder(parentType, handleB);
      return orderA - orderB;
    });
  });

  // Assign layers using BFS from roots (topological order)
  const nodeLayer = new Map<string, number>();
  const rootNodes = nodes.filter(node => inDegree.get(node.id) === 0);

  if (rootNodes.length === 0 && nodes.length > 0) {
    rootNodes.push(nodes[0]); // Fallback if no clear roots
  }

  // BFS to assign layers - node's layer is max(parent layers) + 1
  const queue = rootNodes.map(n => n.id);
  rootNodes.forEach(n => nodeLayer.set(n.id, 0));

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    const currentLayer = nodeLayer.get(nodeId) || 0;

    for (const childId of children.get(nodeId) || []) {
      const existingLayer = nodeLayer.get(childId);
      const newLayer = currentLayer + 1;

      if (existingLayer === undefined || newLayer > existingLayer) {
        nodeLayer.set(childId, newLayer);
      }

      // Add to queue if all parents have been processed
      const childParents = parents.get(childId) || [];
      const allParentsProcessed = childParents.every(p => nodeLayer.has(p));
      if (allParentsProcessed && !queue.includes(childId)) {
        queue.push(childId);
      }
    }
  }

  // Handle any unassigned nodes
  nodes.forEach(node => {
    if (!nodeLayer.has(node.id)) {
      nodeLayer.set(node.id, 0);
    }
  });

  // Group nodes by layer
  const layers = new Map<number, string[]>();
  nodeLayer.forEach((layer, nodeId) => {
    if (!layers.has(layer)) layers.set(layer, []);
    layers.get(layer)!.push(nodeId);
  });

  const maxLayer = Math.max(...Array.from(layers.keys()));

  // Position nodes using CENTER coordinates (not top-left)
  // This ensures nodes of different sizes align by their centers both horizontally and vertically
  const centerPositions = new Map<string, { centerX: number; centerY: number }>();

  // Process layers from rightmost (leaves) to leftmost (roots)
  for (let layer = maxLayer; layer >= 0; layer--) {
    const layerNodes = layers.get(layer) || [];
    const layerNodeObjects = layerNodes.map(id => nodeMap.get(id)!);

    // centerX uses consistent center-to-center spacing across all layers
    // This ensures edges have equal length regardless of node widths
    // startPosition.x + DEFAULT_NODE_WIDTH/2 = center of a default-width node at layer 0
    // Each subsequent layer is spacing.x to the right (center-to-center distance)
    const centerX = opts.startPosition.x + (DEFAULT_NODE_WIDTH / 2) + layer * opts.spacing.x;

    if (layer === maxLayer) {
      // Rightmost layer (leaves) - space nodes evenly by their centers
      const heights = layerNodeObjects.map(n => estimateNodeHeight(n));

      // Calculate spacing needed between centers
      // spacing between centers = (height1/2 + gap + height2/2)
      let totalSpan = 0;
      for (let i = 0; i < heights.length; i++) {
        if (i > 0) {
          totalSpan += opts.spacing.y; // gap
        }
        totalSpan += heights[i];
      }

      // Position first node's center, then space others
      let currentCenterY = opts.startPosition.y - totalSpan / 2 + heights[0] / 2;

      layerNodes.forEach((nodeId, index) => {
        centerPositions.set(nodeId, { centerX, centerY: currentCenterY });
        if (index < heights.length - 1) {
          // Move to next center: half of current height + gap + half of next height
          currentCenterY += heights[index] / 2 + opts.spacing.y + heights[index + 1] / 2;
        }
      });
    } else {
      // Inner layers - center each node based on children's centers
      layerNodes.forEach(nodeId => {
        const nodeChildren = children.get(nodeId) || [];
        const childrenWithPositions = nodeChildren.filter(c => centerPositions.has(c));

        let centerY: number;
        if (childrenWithPositions.length > 0) {
          // Average of children's center Y positions
          const childCenters = childrenWithPositions.map(c => centerPositions.get(c)!.centerY);
          centerY = childCenters.reduce((sum, y) => sum + y, 0) / childCenters.length;
        } else {
          centerY = opts.startPosition.y;
        }

        centerPositions.set(nodeId, { centerX, centerY });
      });

      // Resolve collisions within this layer (using actual bounds)
      const sortedByCenterY = [...layerNodes].sort((a, b) =>
        (centerPositions.get(a)?.centerY || 0) - (centerPositions.get(b)?.centerY || 0)
      );

      for (let i = 1; i < sortedByCenterY.length; i++) {
        const prevNodeId = sortedByCenterY[i - 1];
        const currNodeId = sortedByCenterY[i];
        const prevCenter = centerPositions.get(prevNodeId)!;
        const currCenter = centerPositions.get(currNodeId)!;
        const prevHeight = estimateNodeHeight(nodeMap.get(prevNodeId)!);
        const currHeight = estimateNodeHeight(nodeMap.get(currNodeId)!);

        // Minimum distance between centers to avoid overlap
        const minCenterDistance = prevHeight / 2 + opts.spacing.y + currHeight / 2;

        if (currCenter.centerY - prevCenter.centerY < minCenterDistance) {
          currCenter.centerY = prevCenter.centerY + minCenterDistance;
        }
      }
    }
  }

  // Convert center positions to top-left positions for React Flow
  return nodes.map(node => {
    const centerPos = centerPositions.get(node.id);
    if (!centerPos) {
      return { ...node, position: { x: opts.startPosition.x, y: opts.startPosition.y } };
    }
    const height = estimateNodeHeight(node);
    const width = estimateNodeWidth(node);
    return {
      ...node,
      position: {
        x: centerPos.centerX - width / 2,
        y: centerPos.centerY - height / 2
      }
    };
  });
}

/**
 * Get the next position for a new node based on existing nodes
 */
export function getNextNodePosition(existingNodes: Node[], options?: Partial<LayoutOptions>): { x: number; y: number } {
  const opts = { ...DEFAULT_LAYOUT_OPTIONS, ...options };
  
  if (existingNodes.length === 0) {
    return opts.startPosition;
  }
  
  // Find the rightmost node
  const rightmostNode = existingNodes.reduce((rightmost, node) => 
    node.position.x > rightmost.position.x ? node : rightmost
  );
  
  return {
    x: rightmostNode.position.x + opts.spacing.x,
    y: rightmostNode.position.y
  };
}

/**
 * Layout nodes incrementally as they're added (for animations)
 */
export function addNodeWithAutoLayout(
  existingNodes: Node[], 
  newNode: Node, 
  edges: Edge[],
  options?: Partial<LayoutOptions>
): Node {
  const opts = { ...DEFAULT_LAYOUT_OPTIONS, ...options };
  
  // If this is the first node, place at start position
  if (existingNodes.length === 0) {
    return {
      ...newNode,
      position: opts.startPosition
    };
  }
  
  // Check if this node has any incoming edges from existing nodes
  const incomingFromExisting = edges.filter(edge => 
    edge.target === newNode.id && 
    existingNodes.some(node => node.id === edge.source)
  );
  
  if (incomingFromExisting.length > 0) {
    // Position based on source nodes with consistent Y alignment for straight edges
    const sourceNode = existingNodes.find(node => node.id === incomingFromExisting[0].source);
    if (sourceNode) {
      return {
        ...newNode,
        position: {
          x: sourceNode.position.x + opts.spacing.x,
          y: opts.startPosition.y // Use consistent Y position for all horizontal nodes
        }
      };
    }
  }
  
  // Default: place to the right of the rightmost node
  const position = getNextNodePosition(existingNodes, options);
  return {
    ...newNode,
    position
  };
}