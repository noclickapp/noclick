/**
 * useWorkflowPan - Hook for programmatically panning to nodes/edges in React Flow v12.
 * Handles the complexities of viewport manipulation including FlowHelperView height offset,
 * animation flags to prevent viewport restoration from overriding, and retry logic.
 */

import { useCallback, useRef } from 'react';
import type { Viewport } from '@xyflow/react';

interface UseWorkflowPanOptions {
    /** Height of the FlowHelperView to offset centering */
    flowHelperHeight: number;
    /** Whether the FlowHelperView is actually open — when false the persisted
     *  height is ignored so panning uses the full canvas. Defaults to true. */
    isPanelOpen?: boolean;
    /** State setter for viewport persistence */
    setViewport: (viewport: Viewport) => void;
    /** Default zoom level for panning (default: 1.2) */
    defaultZoom?: number;
    /** Animation duration in ms (default: 400) */
    duration?: number;
}

// Amount of workflow (in world px) we aim to keep framed vertically in the
// strip above the FlowHelperView. When the panel is expanded that strip shrinks,
// so the zoom drops to keep this much in view rather than cramming the node
// edge-to-edge. Floored so we never zoom out into uselessness.
const TARGET_VISIBLE_WORLD_HEIGHT = 450;
const MIN_PAN_ZOOM = 0.8;

/**
 * Optional framing overrides for {@link panToNode}. Omit for the default
 * "center the whole node at an auto fit-zoom" behavior.
 */
export interface PanToNodeOptions {
    /** Normalized point inside the node to bring into focus (0..1 on each axis).
     *  Default {x:0.5, y:0.5} (node center). {x:1, y:0} targets the top-right
     *  corner — e.g. the Publish button that sits flush-right in an interface
     *  node's header — so a large node can't push it off a narrow canvas. */
    focus?: { x: number; y: number };
    /** Where in the visible canvas to place the focus point (0..1). Default
     *  {x:0.5, y:0.5} (dead center). Bias y upward (e.g. 0.26) to leave room
     *  below for a tour tooltip. */
    viewportAnchor?: { x: number; y: number };
    /** Fixed zoom; skips the auto fit-to-node zoom. Anchoring the focus point
     *  keeps it on-screen at any zoom, so a fixed zoom is safe with `focus`. */
    zoom?: number;
}

interface UseWorkflowPanReturn {
    /** Pan and zoom to center a specific node (or a sub-region via options) */
    panToNode: (nodeId: string, options?: PanToNodeOptions) => void;
    /** Pan and zoom to center between two nodes (for edge navigation) */
    panToEdge: (sourceNodeId: string, targetNodeId: string) => void;
    /** Ref to check if animation is in progress - use in viewport restoration useEffect */
    pendingAnimationRef: React.MutableRefObject<boolean>;
}

/**
 * Get the ReactFlow instance stored on window during onInit.
 * This is more reliable than useReactFlow() hook in event listeners.
 */
function getReactFlowInstance() {
    return (window as any).__reactFlowInstance;
}

export function useWorkflowPan({
    flowHelperHeight,
    isPanelOpen = true,
    setViewport,
    defaultZoom = 1.2,
    duration = 400,
}: UseWorkflowPanOptions): UseWorkflowPanReturn {
    const pendingAnimationRef = useRef(false);

    /**
     * Pan to a specific node, centering it in the visible area above FlowHelperView.
     * Includes retry logic if the node isn't rendered yet.
     */
    const panToNode = useCallback((nodeId: string, options?: PanToNodeOptions, retryCount = 0) => {
        const instance = getReactFlowInstance();

        if (!instance || !instance.getNode || !instance.setViewport) {
            // ReactFlow instance not available, retry
            if (retryCount < 10) {
                setTimeout(() => panToNode(nodeId, options, retryCount + 1), 100);
            }
            return;
        }

        const node = instance.getNode(nodeId);
        if (!node) {
            // Node might not be rendered yet, retry
            if (retryCount < 10) {
                setTimeout(() => panToNode(nodeId, options, retryCount + 1), 100);
            }
            return;
        }

        // Validate node has valid position
        if (typeof node.position?.x !== 'number' || typeof node.position?.y !== 'number' ||
            !Number.isFinite(node.position.x) || !Number.isFinite(node.position.y)) {
            if (retryCount < 10) {
                setTimeout(() => panToNode(nodeId, options, retryCount + 1), 100);
            }
            return;
        }

        // Centre on the node's *real* size. ReactFlow stores rendered dimensions
        // on `node.measured`; `node.width`/`node.height` are usually unset (sizing
        // for sticky notes / interface blocks lives in `node.style`). Using the
        // bare 90px fallback mis-centres wide nodes — a 500px block lands ~200px
        // right of centre. Wait for measurement so the maths uses true bounds.
        if ((!node.measured?.width || !node.measured?.height) && retryCount < 10) {
            setTimeout(() => panToNode(nodeId, options, retryCount + 1), 100);
            return;
        }
        const nodeWidth = node.measured?.width || node.width || 90;
        const nodeHeight = node.measured?.height || node.height || 90;

        // Wait for the canvas to actually be mounted and laid out. When a pan is
        // triggered while another tab is active (the publish walkthrough switches
        // to the canvas tab first), the canvas isn't in the DOM yet and
        // window.__reactFlowInstance still points at the previous, unmounted
        // canvas — panning now would mis-fire against stale dimensions. Retrying
        // until the container has real size lets the fresh canvas mount + re-init.
        const container = document.querySelector('[data-testid="flow-canvas"]');
        const containerWidth = container?.clientWidth ?? 0;
        const containerHeight = container?.clientHeight ?? 0;
        if (!containerWidth || !containerHeight) {
            if (retryCount < 10) {
                setTimeout(() => panToNode(nodeId, options, retryCount + 1), 100);
            }
            return;
        }
        const panelHeight = isPanelOpen ? flowHelperHeight : 0;
        const visibleHeight = containerHeight - panelHeight;

        // The point inside the node to bring into view, and where in the visible
        // canvas to place it. Defaults reproduce the legacy "center the whole
        // node" behavior; callers can anchor a sub-region (e.g. the top-right
        // Publish button) so a large node can't push it off a narrow canvas.
        const focus = options?.focus ?? { x: 0.5, y: 0.5 };
        const viewportAnchor = options?.viewportAnchor ?? { x: 0.5, y: 0.5 };
        const focusX = node.position.x + nodeWidth * focus.x;
        const focusY = node.position.y + nodeHeight * focus.y;

        // Auto fit-to-node zoom (centers the whole node): zoom out when the
        // visible strip is short (helper expanded) so the node keeps context,
        // and guarantee the node itself fits. Callers anchoring a sub-region
        // pass an explicit zoom instead — the MIN_PAN_ZOOM floor below can
        // otherwise render a large node bigger than the canvas and push that
        // sub-region (e.g. a corner button) off-screen.
        const zoom = options?.zoom ?? Math.max(
            MIN_PAN_ZOOM,
            Math.min(
                defaultZoom,
                visibleHeight / TARGET_VISIBLE_WORLD_HEIGHT,
                (visibleHeight * 0.8) / nodeHeight,
                (containerWidth * 0.85) / nodeWidth,
            ),
        );

        const targetX = -focusX * zoom + containerWidth * viewportAnchor.x;
        const targetY = -focusY * zoom + visibleHeight * viewportAnchor.y;
        const targetViewport = { x: targetX, y: targetY, zoom };

        // Final validation - ensure no NaN values
        if (!Number.isFinite(targetX) || !Number.isFinite(targetY)) {
            if (retryCount < 10) {
                setTimeout(() => panToNode(nodeId, options, retryCount + 1), 100);
            }
            return;
        }

        // Mark animation as in progress to prevent viewport restoration useEffect
        // from overriding our animated viewport change
        pendingAnimationRef.current = true;

        // Update the viewport state for persistence
        setViewport(targetViewport);

        // Animate to the new viewport
        instance.setViewport(targetViewport, { duration });

        // Clear the animation flag after animation completes
        setTimeout(() => {
            pendingAnimationRef.current = false;
        }, duration + 50);
    }, [flowHelperHeight, isPanelOpen, setViewport, defaultZoom, duration]);

    /**
     * Pan to center between two nodes (useful for edge navigation).
     * Calculates bounding box and adjusts zoom based on distance.
     */
    const panToEdge = useCallback((sourceNodeId: string, targetNodeId: string, retryCount = 0) => {
        const instance = getReactFlowInstance();

        if (!instance || !instance.getNode || !instance.setViewport) {
            if (retryCount < 10) {
                setTimeout(() => panToEdge(sourceNodeId, targetNodeId, retryCount + 1), 100);
            }
            return;
        }

        const sourceNode = instance.getNode(sourceNodeId);
        const targetNode = instance.getNode(targetNodeId);

        if (!sourceNode && !targetNode) {
            if (retryCount < 10) {
                setTimeout(() => panToEdge(sourceNodeId, targetNodeId, retryCount + 1), 100);
            }
            return;
        }

        // Calculate bounding box of both nodes
        const nodesToFit = [sourceNode, targetNode].filter(Boolean);
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;

        for (const node of nodesToFit) {
            if (!node) continue;
            const nodeWidth = node.width || 90;
            const nodeHeight = node.height || 90;
            minX = Math.min(minX, node.position.x);
            maxX = Math.max(maxX, node.position.x + nodeWidth);
            minY = Math.min(minY, node.position.y);
            maxY = Math.max(maxY, node.position.y + nodeHeight);
        }

        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;

        // Calculate zoom based on distance between nodes
        const boundingWidth = maxX - minX;
        const boundingHeight = maxY - minY;
        // Calculate target viewport
        const container = document.querySelector('[data-testid="flow-canvas"]');
        const containerWidth = container?.clientWidth || window.innerWidth;
        const containerHeight = container?.clientHeight || window.innerHeight;
        const panelHeight = isPanelOpen ? flowHelperHeight : 0;
        const visibleHeight = containerHeight - panelHeight;

        // Zoom to fit both nodes' span, the expanded-helper strip, and the
        // distance between them — whichever is tightest.
        const maxDimension = Math.max(boundingWidth, boundingHeight, 200);
        const zoom = Math.max(
            MIN_PAN_ZOOM,
            Math.min(
                defaultZoom,
                400 / maxDimension,
                visibleHeight / TARGET_VISIBLE_WORLD_HEIGHT,
            ),
        );

        const targetX = -centerX * zoom + containerWidth / 2;
        const targetY = -centerY * zoom + visibleHeight / 2;
        const targetViewport = { x: targetX, y: targetY, zoom };

        if (!Number.isFinite(targetX) || !Number.isFinite(targetY)) {
            return;
        }

        pendingAnimationRef.current = true;
        setViewport(targetViewport);
        instance.setViewport(targetViewport, { duration });

        setTimeout(() => {
            pendingAnimationRef.current = false;
        }, duration + 50);
    }, [flowHelperHeight, isPanelOpen, setViewport, defaultZoom, duration]);

    return {
        panToNode,
        panToEdge,
        pendingAnimationRef,
    };
}
