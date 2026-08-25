// IncompleteNodeNavigator displays a yellow pill indicator for nodes with incomplete configuration.
// It shows the count of incomplete nodes and allows cycling through them with left/right navigation.
// It used to offer a "Guided Setup" hand-off into the Setup tab; that tab now exists only for the
// setup-node-driven template flow, so incomplete nodes are fixed in place via the config panel.
//
// Source of truth: getIncompleteNodes(nodes) (synchronous, calls validateNode).
// FlowCanvas's debounced `configValid` flag is for per-node yellow borders only;
// the pill always reflects current node state with no debounce lag.
//
// Renders the pill only — CanvasNavigatorPills owns where it sits. It used to
// place itself at a hardcoded left offset that guessed the red error pill's
// width, which left a ~30px gap beside it (and would have overlapped once the
// counts reached three digits).

import { useState, useEffect, useMemo, memo } from 'react';
import { Node } from '@xyflow/react';
import { ChevronLeft, ChevronRight, AlertCircle } from 'lucide-react';
import { getIncompleteNodes, getNodeIssueSummary, type NodeValidationContext } from '~/utils/workflowNodeValidation';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';

interface IncompleteNodeNavigatorProps {
    nodes: Node[];
    /** Precomputed, content-stable wiring context (agent tool-provider mode).
     *  Stable identity prevents edges-selection churn from re-running the
     *  full validation memo. */
    validationContext?: NodeValidationContext;
    selectedNodeId: string | null;
    onNavigateToNode: (nodeId: string) => void;
}

export const IncompleteNodeNavigator = memo(function IncompleteNodeNavigator({
    nodes,
    validationContext,
    selectedNodeId,
    onNavigateToNode,
}: IncompleteNodeNavigatorProps) {
    // Run validateNode per node on each render. Cheap (< 1ms for typical
    // workflows), runs against the latest data so there's no debounce window
    // where the pill disagrees with what the user just changed. FlowCanvas
    // freezes `nodes` during drag (via stableNodesForNav), so the memo only
    // recomputes when meaningful state changes.
    const incompleteNodes = useMemo(
        () => getIncompleteNodes(nodes, validationContext),
        [nodes, validationContext]
    );
    const incompleteCount = incompleteNodes.length;

    // Track current index in the incomplete nodes list
    const [currentIndex, setCurrentIndex] = useState(0);

    // Sync currentIndex when selectedNode changes externally
    useEffect(() => {
        if (selectedNodeId && incompleteNodes.length > 0) {
            const idx = incompleteNodes.findIndex(n => n.id === selectedNodeId);
            if (idx !== -1 && idx !== currentIndex) {
                setCurrentIndex(idx);
            }
        }
    }, [selectedNodeId, incompleteNodes, currentIndex]);

    // Reset index when incomplete list changes
    useEffect(() => {
        if (currentIndex >= incompleteNodes.length) {
            setCurrentIndex(Math.max(0, incompleteNodes.length - 1));
        }
    }, [incompleteNodes.length, currentIndex]);

    // Get the current node's ID for stable dependency tracking
    const currentNodeId = incompleteNodes[currentIndex]?.id;

    // Get issue summary for current node - only recalculate when the actual node changes
    // Uses currentNodeId as dependency to avoid re-running validateNode during drag
    // validationContext is a real dep now that validation is wiring-aware
    // (provider mode): a wiring change can flip the issue message without
    // changing the incomplete count or the focused node id.
    const currentIssueSummary = useMemo(() => {
        if (!currentNodeId || incompleteNodes.length === 0) return '';
        const currentNode = incompleteNodes.find(n => n.id === currentNodeId);
        if (!currentNode) return '';
        return getNodeIssueSummary(currentNode, validationContext);
    }, [currentNodeId, incompleteNodes, validationContext]);

    if (incompleteCount === 0) {
        return null;
    }

    // Arriving at a node makes the config panel's amber banner pulse — the
    // banner does that itself on arrival (IncompleteConfigBanner), so there's
    // nothing to coordinate from here.

    // Navigate to previous incomplete node
    const handlePrevious = () => {
        const newIndex = currentIndex === 0 ? incompleteCount - 1 : currentIndex - 1;
        setCurrentIndex(newIndex);
        onNavigateToNode(incompleteNodes[newIndex].id);
    };

    // Navigate to next incomplete node
    const handleNext = () => {
        const newIndex = currentIndex === incompleteCount - 1 ? 0 : currentIndex + 1;
        setCurrentIndex(newIndex);
        onNavigateToNode(incompleteNodes[newIndex].id);
    };

    return (
        <IncompleteNodeNavigatorPill
            incompleteCount={incompleteCount}
            currentIndex={currentIndex}
            currentIssueSummary={currentIssueSummary}
            onPrevious={handlePrevious}
            onNext={handleNext}
        />
    );
});

interface IncompleteNodeNavigatorPillProps {
    incompleteCount: number;
    currentIndex: number;
    currentIssueSummary: string;
    onPrevious: () => void;
    onNext: () => void;
}

// Presentational pill, split out from the hook-owning component above so the
// early return for "nothing incomplete" doesn't sit among the hooks.
function IncompleteNodeNavigatorPill({
    incompleteCount,
    currentIndex,
    currentIssueSummary,
    onPrevious,
    onNext,
}: IncompleteNodeNavigatorPillProps) {
    return (
        <TooltipProvider>
            <div className="flex items-center gap-1 px-2 py-1.5 rounded-full border border-amber-300 bg-amber-100 dark:border-amber-500/40 dark:bg-amber-500/15 backdrop-blur-sm">
                <button
                    onClick={onPrevious}
                    className="p-1 rounded-full hover:bg-amber-500/20 transition-colors text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                    title="Previous incomplete node"
                >
                    <ChevronLeft className="w-4 h-4" />
                </button>

                <Tooltip>
                    <TooltipTrigger asChild>
                        <div className="flex items-center gap-1.5 cursor-default">
                            <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                            <span className="text-xs font-semibold text-amber-700 dark:text-amber-300 tabular-nums">
                                {`${currentIndex + 1} / ${incompleteCount}`}
                            </span>
                        </div>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="bg-card border-border dark:border-zinc-700 text-popover-foreground dark:text-zinc-200">
                        <p className="text-xs">
                            {currentIssueSummary || 'Nodes need configuration'}
                        </p>
                    </TooltipContent>
                </Tooltip>

                <button
                    onClick={onNext}
                    className="p-1 rounded-full hover:bg-amber-500/20 transition-colors text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                    title="Next incomplete node"
                >
                    <ChevronRight className="w-4 h-4" />
                </button>
            </div>
        </TooltipProvider>
    );
}
