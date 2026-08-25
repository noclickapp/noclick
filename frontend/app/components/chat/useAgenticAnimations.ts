/**
 * useAgenticAnimations Hook
 * 
 * Handles DOM operations and smooth width animations for reasoning section collapse/expand.
 * DOM measurement is needed because CSS can't animate from dynamic content width to collapsed
 * width without knowing both values. Timing coordination prevents visual snapping. This is
 * needed when reasoning is collapsed and expanded to resize the message container to the
 * ideal width.
 */

import { useState, useCallback, useRef } from 'react';

interface UseAgenticAnimationsReturn {
    hiddenFromLayout: Record<number, boolean>;
    collapsedWidths: Record<number, number>;
    animatingWidths: Record<number, { from: number; to: number }>;
    messageRefs: React.MutableRefObject<Record<number, HTMLDivElement | null>>;
    measureCollapsedWidth: (messageIndex: number) => number | null;
    startCollapseAnimation: (messageIndex: number, isCurrentlyCollapsed: boolean) => void;
}

export const useAgenticAnimations = (): UseAgenticAnimationsReturn => {
    // Keep track of which reasoning sections should be hidden from layout after animation
    const [hiddenFromLayout, setHiddenFromLayout] = useState<Record<number, boolean>>({});
    // Store measured collapsed widths for each message
    const [collapsedWidths, setCollapsedWidths] = useState<Record<number, number>>({});
    // Track messages currently animating width during collapse
    const [animatingWidths, setAnimatingWidths] = useState<Record<number, { from: number; to: number }>>({});
    const messageRefs = useRef<Record<number, HTMLDivElement | null>>({});

    const measureCollapsedWidth = useCallback((messageIndex: number) => {
        const messageElement = messageRefs.current[messageIndex];
        if (!messageElement) return null;
        
        // Find the expanded reasoning content (not the button)
        const expandedContent = messageElement.querySelector('[data-reasoning-content]') as HTMLElement;
        const reasoningButton = messageElement.querySelector('[data-reasoning-button]') as HTMLElement;
        if (!expandedContent) return null;
        
        // Temporarily hide the expanded content but keep the "Reasoning (X steps)" button
        const originalDisplay = expandedContent.style.display;
        const originalWhiteSpace = reasoningButton?.style.whiteSpace || '';
        
        expandedContent.style.display = 'none';
        // Prevent button text from wrapping during measurement
        if (reasoningButton) {
            reasoningButton.style.whiteSpace = 'nowrap';
        }
        
        // Force reflow and measure
        messageElement.offsetHeight;
        const collapsedWidth = messageElement.offsetWidth;
        
        // Restore the content and button styles
        expandedContent.style.display = originalDisplay;
        if (reasoningButton) {
            reasoningButton.style.whiteSpace = originalWhiteSpace;
        }
        
        return collapsedWidth;
    }, []);

    const startCollapseAnimation = useCallback((messageIndex: number, isCurrentlyCollapsed: boolean) => {
        const messageElement = messageRefs.current[messageIndex];
        
        if (isCurrentlyCollapsed) {
            // Expanding: clear any width animations and expand normally
            setAnimatingWidths(prev => {
                const newState = { ...prev };
                delete newState[messageIndex];
                return newState;
            });
            setHiddenFromLayout(prev => ({
                ...prev,
                [messageIndex]: false
            }));
        } else {
            // Collapsing: only do width animation if we have a cached collapsed width
            if (messageElement && collapsedWidths[messageIndex]) {
                const currentWidth = messageElement.offsetWidth;
                const targetWidth = collapsedWidths[messageIndex];
                
                if (targetWidth !== currentWidth) {
                    // First, fix the current width to establish baseline
                    setAnimatingWidths(prev => ({
                        ...prev,
                        [messageIndex]: { from: currentWidth, to: currentWidth }
                    }));
                    
                    // Start width animation in the next frame
                    requestAnimationFrame(() => {
                        setAnimatingWidths(prev => ({
                            ...prev,
                            [messageIndex]: { from: currentWidth, to: targetWidth }
                        }));
                    });
                }
                
                // After animation completes, hide content and clear width animation
                setTimeout(() => {
                    setHiddenFromLayout(prev => ({
                        ...prev,
                        [messageIndex]: true
                    }));
                    // Always clear the width animation after content collapse
                    setAnimatingWidths(prev => {
                        const newState = { ...prev };
                        delete newState[messageIndex];
                        return newState;
                    });
                }, 300);
            } else if (messageElement) {
                // First collapse: measure collapsed width after CSS transition completes
                setTimeout(() => {
                    const targetWidth = measureCollapsedWidth(messageIndex);
                    if (targetWidth) {
                        setCollapsedWidths(prev => ({
                            ...prev,
                            [messageIndex]: targetWidth
                        }));
                    }
                    setHiddenFromLayout(prev => ({
                        ...prev,
                        [messageIndex]: true
                    }));
                }, 300);
            }
        }
    }, [collapsedWidths, measureCollapsedWidth]);

    return {
        hiddenFromLayout,
        collapsedWidths,
        animatingWidths,
        messageRefs,
        measureCollapsedWidth,
        startCollapseAnimation,
    };
};