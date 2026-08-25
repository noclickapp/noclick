// ErrorNodeNavigator component displays a circular indicator showing the count of errored nodes
// and allows cycling through them with left/right navigation buttons.
// Used in FlowCanvas to help users quickly find and fix all workflow errors.
//
// Renders the pill only — CanvasNavigatorPills owns where it sits, so it and the
// amber incomplete pill stay a fixed gap apart whatever width their counts take.

import { useState, useEffect, useMemo, memo } from 'react';
import { Node } from '@xyflow/react';
import { ChevronLeft, ChevronRight, AlertTriangle } from 'lucide-react';

interface ErrorNodeNavigatorProps {
    nodes: Node[];
    selectedNodeId: string | null;
    onNavigateToNode: (nodeId: string) => void;
}

export const ErrorNodeNavigator = memo(function ErrorNodeNavigator({
    nodes,
    selectedNodeId,
    onNavigateToNode,
}: ErrorNodeNavigatorProps) {
    // Get all nodes with errors
    const erroredNodes = useMemo(() => {
        return nodes.filter(n => n.data?.executionState === 'error');
    }, [nodes]);

    const errorCount = erroredNodes.length;

    // Track current index in the errored nodes list
    const [currentIndex, setCurrentIndex] = useState(0);

    // Sync currentIndex when selectedNode changes externally
    useEffect(() => {
        if (selectedNodeId && erroredNodes.length > 0) {
            const idx = erroredNodes.findIndex(n => n.id === selectedNodeId);
            if (idx !== -1 && idx !== currentIndex) {
                setCurrentIndex(idx);
            }
        }
    }, [selectedNodeId, erroredNodes, currentIndex]);

    // Reset index when error list changes
    useEffect(() => {
        if (currentIndex >= erroredNodes.length) {
            setCurrentIndex(Math.max(0, erroredNodes.length - 1));
        }
    }, [erroredNodes.length, currentIndex]);

    // Navigate to previous errored node
    const handlePrevious = () => {
        if (errorCount === 0) return;
        const newIndex = currentIndex === 0 ? errorCount - 1 : currentIndex - 1;
        setCurrentIndex(newIndex);
        onNavigateToNode(erroredNodes[newIndex].id);
    };

    // Navigate to next errored node
    const handleNext = () => {
        if (errorCount === 0) return;
        const newIndex = currentIndex === errorCount - 1 ? 0 : currentIndex + 1;
        setCurrentIndex(newIndex);
        onNavigateToNode(erroredNodes[newIndex].id);
    };

    // Don't render if no errors
    if (errorCount === 0) {
        return null;
    }

    return (
        <div className="flex items-center gap-1 px-2 py-1.5 rounded-full border border-red-500/40 bg-red-500/20 backdrop-blur-sm">
            {/* Previous button */}
            <button
                onClick={handlePrevious}
                className="p-1 rounded-full hover:bg-red-500/20 transition-colors text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                title="Previous error"
            >
                <ChevronLeft className="w-4 h-4" />
            </button>

            {/* Error count indicator. No horizontal padding of its own —
                the row's gap-1 already separates it from the chevrons, and
                doubling the two left a 12px chevron gap against a 6px
                icon-to-count gap. Mirrored in IncompleteNodeNavigator. */}
            <div className="flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400" />
                <span className="text-xs font-semibold text-red-700 dark:text-red-300 tabular-nums">
                    {currentIndex + 1} / {errorCount}
                </span>
            </div>

            {/* Next button */}
            <button
                onClick={handleNext}
                className="p-1 rounded-full hover:bg-red-500/20 transition-colors text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                title="Next error"
            >
                <ChevronRight className="w-4 h-4" />
            </button>
        </div>
    );
});
