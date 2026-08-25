/**
 * useAutoLayout - Enhanced layout system that works with virtual layout predictions.
 * Provides manual layout triggers and layout validation, while working seamlessly with virtual positioning.
 * Reduced role in workflow animations as nodes are now placed at predicted positions directly.
 */
import { useCallback, useEffect, useState, useRef } from 'react';
import { Node, useReactFlow } from '@xyflow/react';
import { useLayoutCalculation } from './useLayoutCalculation';
import { useManuallyMovedNodes } from './useManuallyMovedNodes';

export interface LayoutConfig {
  direction: 'TB' | 'BT' | 'LR' | 'RL';
  nodeSpacing: { x: number; y: number };
  levelSpacing: number;
  enableAutoLayout: boolean;
}

export interface UseAutoLayoutOptions {
  config?: Partial<LayoutConfig>;
  onLayoutStart?: () => void;
  onLayoutComplete?: (nodes: Node[]) => void;
}

interface UseAutoLayoutReturn {
  layoutNodes: () => Promise<void>;
  isLayouting: boolean;
  config: LayoutConfig;
  updateConfig: (newConfig: Partial<LayoutConfig>) => void;
}

const DEFAULT_CONFIG: LayoutConfig = {
  direction: 'LR', // Left to Right for workflow
  nodeSpacing: { x: 200, y: 250 }, // Spacing between sibling nodes - matches FlowCanvas and virtual layout
  levelSpacing: 120, // Spacing between hierarchy levels - matches FlowCanvas and virtual layout
  enableAutoLayout: true
};


export const useAutoLayout = ({
  config: userConfig,
  onLayoutStart,
  onLayoutComplete
}: UseAutoLayoutOptions = {}): UseAutoLayoutReturn => {
  const { setNodes, getNodes, getEdges } = useReactFlow();
  
  const [isLayouting, setIsLayouting] = useState(false);
  const [config, setConfig] = useState<LayoutConfig>({
    ...DEFAULT_CONFIG,
    ...userConfig
  });
  
  // Use shared layout calculation
  const { calculateLayout } = useLayoutCalculation();
  
  // Use shared manual node detection
  const { detectManuallyMovedNodes } = useManuallyMovedNodes();
  
  // Track the last layout state to prevent unnecessary recalculations
  const lastLayoutSignature = useRef<string>('');
  
  // Debouncing system to prevent rapid successive layout calls
  const layoutTimeoutRef = useRef<NodeJS.Timeout | null>(null);


  /**
   * Enhanced layout function that works with virtual layout predictions
   * Primarily used for manual layout triggers and layout validation
   */
  const debouncedLayoutNodes = useCallback(async (forceLayout: boolean = false, respectManualPositions: boolean = true): Promise<void> => {
    try {
      if (!config.enableAutoLayout || isLayouting) {
        return;
      }
      
      const nodes = getNodes();
      const edges = getEdges();
    
    if (nodes.length === 0) {
      return;
    }
    
    // Create signature for change detection (excluding positions since we reset them)
    const signature = `${nodes.length}-${edges.length}-${nodes.map(n => n.id).sort().join(',')}-${edges.map(e => `${e.source}-${e.target}`).sort().join(',')}`;
    
    // Skip layout if nothing significant changed (unless forced)
    if (!forceLayout && signature === lastLayoutSignature.current) {
      return;
    }
    lastLayoutSignature.current = signature;
    
    setIsLayouting(true);
    onLayoutStart?.();
    
    try {
      // Use shared layout calculation
      let finalNodes = calculateLayout(nodes, edges, config);
      
      // Only preserve manually moved nodes if respectManualPositions is true
      if (respectManualPositions) {
        // Detect which nodes have been manually moved
        const manuallyMovedIds = detectManuallyMovedNodes(nodes, edges, config);
        
        // Preserve positions of manually moved nodes
        finalNodes = finalNodes.map(node => {
          if (manuallyMovedIds.has(node.id)) {
            // Find the original node to preserve its position
            const originalNode = nodes.find(n => n.id === node.id);
            if (originalNode) {
              return { ...node, position: originalNode.position };
            }
          }
          return node;
        });
      }
      
      setNodes(finalNodes);
      
      // Auto layout positioning complete - no automatic panning
      
      onLayoutComplete?.(finalNodes);
    } catch (error) {
      console.error('Auto layout failed:', error);
    } finally {
      setIsLayouting(false);
    }
    } catch (outerError) {
      console.error('Auto layout error:', outerError);
      setIsLayouting(false);
    }
  }, [
    config,
    isLayouting,
    getNodes,
    getEdges,
    calculateLayout,
    detectManuallyMovedNodes,
    setNodes,
    onLayoutStart,
    onLayoutComplete
  ]);

  /**
   * Main layout function with reduced debouncing (since layout is called less frequently now)
   * When called directly (e.g., from Auto Layout button), it doesn't respect manual positions
   */
  const layoutNodes = useCallback((forceLayout: boolean = true): Promise<void> => {
    return new Promise((resolve, reject) => {
      // Clear any existing timeout to debounce rapid calls
      if (layoutTimeoutRef.current) {
        clearTimeout(layoutTimeoutRef.current);
      }
      
      // Set new timeout for debounced execution
      layoutTimeoutRef.current = setTimeout(async () => {
        try {
          // When explicitly called (like from Auto Layout button), don't respect manual positions
          await debouncedLayoutNodes(forceLayout, false);
          resolve();
        } catch (error) {
          reject(error);
        }
      }, 100); // Increased to 100ms since layout is less frequent and more intentional
    });
  }, [debouncedLayoutNodes]);

  /**
   * Update layout configuration
   */
  const updateConfig = useCallback((newConfig: Partial<LayoutConfig>) => {
    setConfig(prev => ({ ...prev, ...newConfig }));
    // Reset layout signature to force recalculation
    lastLayoutSignature.current = '';
  }, []);


  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (layoutTimeoutRef.current) {
        clearTimeout(layoutTimeoutRef.current);
      }
    };
  }, []);

  return {
    layoutNodes,
    isLayouting,
    config,
    updateConfig
  };
};