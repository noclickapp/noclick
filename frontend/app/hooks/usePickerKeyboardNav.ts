// Shared keyboard-navigation scaffolding for searchable picker panels
// (OperationPicker, AgentToolOperationsPicker). Owns the highlight state, the
// user-navigation-gated scrollIntoView (mount/open must not yank the panel),
// and the triple-stop key handling ReactFlow's native listeners require.
// Navigation strategy is pluggable: 2D nearest-in-direction for the tile
// grid, linear up/down for row lists.

import { useEffect, useRef, useState } from 'react';

export type PickerNavDirection = 'up' | 'down' | 'left' | 'right';

interface UsePickerKeyboardNavOptions {
    /** Number of navigable items (flat reading order, 0..itemCount-1). */
    itemCount: number;
    /** Scroll container holding elements tagged data-flat-index. */
    containerRef: React.RefObject<HTMLElement | null>;
    /** Next index for an arrow press, or null to stay put. */
    resolveNext: (direction: PickerNavDirection, current: number) => number | null;
    /** Enter on the highlighted item. */
    onCommit: (index: number) => void;
}

export function usePickerKeyboardNav({
    itemCount,
    containerRef,
    resolveNext,
    onCommit,
}: UsePickerKeyboardNavOptions) {
    const [highlightedIndex, setHighlightedIndex] = useState(0);
    /** Tracks whether the user has driven a highlight change since the picker
     *  opened/mounted. scrollIntoView is gated on this so the initial
     *  highlight (e.g. auto-set to the current selection on open) doesn't
     *  yank the panel down to a mid-list position. */
    const hasUserNavigatedRef = useRef(false);

    // Reset highlight when the visible set changes (search filtering).
    useEffect(() => {
        setHighlightedIndex(0);
    }, [itemCount]);

    // Scroll the highlighted item into view ONLY when the user actively
    // navigated to it (arrow keys) — mouse-enter highlights and programmatic
    // resets don't need scrolling.
    useEffect(() => {
        if (!hasUserNavigatedRef.current) return;
        const el = containerRef.current?.querySelector(
            `[data-flat-index="${highlightedIndex}"]`,
        );
        el?.scrollIntoView({ block: 'nearest' });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [highlightedIndex]);

    /** Clear the navigation gate (call when the picker closes) so the next
     *  open starts fresh. */
    const resetNavigation = () => {
        hasUserNavigatedRef.current = false;
    };

    /** Arrows + Enter. Captured keys are stopped at every level — React's
     *  stopPropagation alone doesn't cut it because ReactFlow + the sidebar
     *  attach native window/document listeners outside React's event tree.
     *  Other keys (Escape, typing) pass through untouched for the caller. */
    const handleKeyDown = (e: React.KeyboardEvent) => {
        const handled = () => {
            e.preventDefault();
            e.stopPropagation();
            e.nativeEvent.stopImmediatePropagation();
        };
        switch (e.key) {
            case 'ArrowDown':
            case 'ArrowUp':
            case 'ArrowLeft':
            case 'ArrowRight': {
                handled();
                const direction = e.key.replace('Arrow', '').toLowerCase() as PickerNavDirection;
                const next = resolveNext(direction, highlightedIndex);
                if (next !== null) {
                    hasUserNavigatedRef.current = true;
                    setHighlightedIndex(next);
                }
                break;
            }
            case 'Enter':
                handled();
                if (itemCount > 0) onCommit(highlightedIndex);
                break;
        }
    };

    return { highlightedIndex, setHighlightedIndex, resetNavigation, handleKeyDown };
}
