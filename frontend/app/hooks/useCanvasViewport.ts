import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { Viewport } from '@xyflow/react';
import { getCachedViewport, setCachedViewport } from '~/lib/viewportCache';

// Defensive validator — ReactFlow sometimes hands us NaN viewports during
// transient states (mid-animation, zeroed container) and we'd rather ignore
// those than persist corrupt values.
export function isValidViewport(vp: unknown): vp is Viewport {
    if (!vp || typeof vp !== 'object') return false;
    const v = vp as { x?: unknown; y?: unknown; zoom?: unknown };
    return (
        typeof v.x === 'number' && Number.isFinite(v.x) &&
        typeof v.y === 'number' && Number.isFinite(v.y) &&
        typeof v.zoom === 'number' && Number.isFinite(v.zoom) && v.zoom > 0
    );
}

interface UseCanvasViewportParams {
    workflowId?: string;
    isReactFlowReady: boolean;
    /** True once workflow:get has returned — we only apply the stored viewport after that. */
    hasLoadedWorkflow: boolean;
    /** Tracks in-flight programmatic animations (pan-to-node) so we don't fight them. */
    pendingAnimationRef: React.MutableRefObject<boolean>;
    /** Current persisted viewport (from useWorkflowDisplayMetadata). */
    viewport: Viewport;
    setViewport: (vp: Viewport) => void;
    /** ReactFlow instance methods. */
    setReactFlowViewport: (vp: Viewport, options?: { duration?: number }) => void;
    fitView: (options: { padding: number; duration: number; maxZoom?: number }) => void;
    getViewport: () => Viewport;
    /** Increments when backend load finishes — retriggers the apply effect. */
    workflowLoadedTrigger: number;
    /** Layout inputs used to shift the fitted viewport above the FlowHelperView. */
    isConfigViewExpanded: boolean;
    isFlowHelperFullScreen: boolean;
    flowHelperHeight: number;
    isMobile: boolean;
    /** Count (not the array) — we just need to know if any nodes exist for auto-fit. */
    nodeCount: number;
    isSyncing: boolean;
    /** Called when ReactFlow mounts (from the returned `onInit`). */
    setIsReactFlowReady: (ready: boolean) => void;
}

// Owns all viewport plumbing for the canvas:
//
// - `safeViewport`: memo for ReactFlow's `defaultViewport` prop with instant
//   restore from the module-level cache (prevents zoom flash on remount).
// - `onInit`: fires when ReactFlow mounts — stashes the instance + applies
//   any restored viewport.
// - `onMoveEnd`: persists the viewport to both the metadata store and the
//   module cache on every user-driven pan/zoom end.
// - Effect: on first successful load of a workflow, applies a stored non-default
//   viewport; otherwise auto-fits once (with mobile padding) and shifts up
//   to leave room for the FlowHelperView if expanded.
export function useCanvasViewport({
    workflowId,
    isReactFlowReady,
    hasLoadedWorkflow,
    pendingAnimationRef,
    viewport,
    setViewport,
    setReactFlowViewport,
    fitView,
    getViewport,
    workflowLoadedTrigger,
    isConfigViewExpanded,
    isFlowHelperFullScreen,
    flowHelperHeight,
    isMobile,
    nodeCount,
    isSyncing,
    setIsReactFlowReady,
}: UseCanvasViewportParams) {
    // These refs gate the "apply once per workflow" logic in the effect below.
    const hasAppliedViewportRef = useRef(false);
    const hasAutoFittedRef = useRef(false);

    // Reset the one-shot flags when the user opens a different workflow.
    useEffect(() => {
        hasAppliedViewportRef.current = false;
        hasAutoFittedRef.current = false;
    }, [workflowId]);

    // Apply / auto-fit effect. Runs whenever the viewport or one of the layout
    // inputs changes, but the inner refs ensure we only act on the first load.
    useEffect(() => {
        if (!isReactFlowReady || !hasLoadedWorkflow) return;
        // A pan-to-node animation is in flight — don't clobber it.
        if (pendingAnimationRef.current) return;

        const isNonDefault = viewport.x !== 0 || viewport.y !== 0 || viewport.zoom !== 1;
        if (isNonDefault && isValidViewport(viewport) && !hasAppliedViewportRef.current) {
            hasAppliedViewportRef.current = true;
            setReactFlowViewport(viewport, { duration: 0 });
            if (workflowId) setCachedViewport(workflowId, viewport);
        } else if (!hasAppliedViewportRef.current) {
            // defaultViewport may have picked this up already, but ReactFlow's
            // internal state might not match — sync it explicitly.
            const cached = workflowId ? getCachedViewport(workflowId) : null;
            if (cached && isValidViewport(cached) && (cached.x !== 0 || cached.y !== 0 || cached.zoom !== 1)) {
                hasAppliedViewportRef.current = true;
                setReactFlowViewport(cached, { duration: 0 });
            }
        }

        if (nodeCount > 0 && !hasAutoFittedRef.current && !hasAppliedViewportRef.current && !isSyncing) {
            // No saved viewport + workflow has nodes → auto-fit once.
            hasAutoFittedRef.current = true;
            hasAppliedViewportRef.current = true;
            setTimeout(() => {
                // Mobile gets more padding so nodes don't hug the edges.
                const padding = isMobile ? 0.25 : 0.15;
                fitView({ padding, duration: 0, maxZoom: isMobile ? 1.0 : 1.5 });

                // On desktop with the helper expanded, shift up so nodes aren't hidden.
                if (!isMobile && isConfigViewExpanded && !isFlowHelperFullScreen && flowHelperHeight > 0) {
                    const currentViewport = getViewport();
                    // 65% of the helper height (flow-coords = screen px / zoom)
                    const shiftY = (flowHelperHeight * 0.65) / currentViewport.zoom;
                    setReactFlowViewport(
                        { ...currentViewport, y: currentViewport.y - shiftY },
                        { duration: 300 }
                    );
                }
            }, 100);
        }
    // The plan intentionally excludes some deps to avoid re-firing while state
    // settles — preserving the original eslint-disable behaviour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isReactFlowReady, viewport, nodeCount, workflowLoadedTrigger, isConfigViewExpanded, isFlowHelperFullScreen, flowHelperHeight, isMobile]);

    // Safe viewport for ReactFlow's defaultViewport — prefers the instant
    // module-level cache to prevent zoom flash before displayMetadata hydrates.
    const safeViewport = useMemo(() => {
        const cached = workflowId ? getCachedViewport(workflowId) : null;
        if (cached && isValidViewport(cached)) return cached;
        if (isValidViewport(viewport)) return viewport;
        return { x: 0, y: 0, zoom: 1 };
    }, [viewport, workflowId]);

    const onInit = useCallback((instance: { setViewport: (vp: Viewport) => void }) => {
        setIsReactFlowReady(true);
        // Expose for pan-to-node (fires setViewport programmatically)
        (window as unknown as { __reactFlowInstance?: typeof instance }).__reactFlowInstance = instance;
        if (isValidViewport(viewport) && (viewport.x !== 0 || viewport.y !== 0 || viewport.zoom !== 1)) {
            instance.setViewport(viewport);
        }
    }, [viewport, setIsReactFlowReady]);

    const onMoveEnd = useCallback((_event: unknown, newViewport: unknown) => {
        if (!isValidViewport(newViewport)) return;
        setViewport(newViewport);
        if (workflowId) setCachedViewport(workflowId, newViewport);
    }, [setViewport, workflowId]);

    return { safeViewport, onInit, onMoveEnd };
}
