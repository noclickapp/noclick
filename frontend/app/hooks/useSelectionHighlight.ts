// Custom hook to detect when an element is within the text selection range
// Used to apply visual highlighting to inline tags when they're selected with text

import { useEffect, useState, RefObject } from 'react';

/**
 * Hook that tracks whether an element is within the current text selection
 * @param elementRef - Reference to the element to track
 * @returns boolean indicating if element is within selection
 */
export function useSelectionHighlight(elementRef: RefObject<HTMLElement | null>): boolean {
    const [isSelected, setIsSelected] = useState(false);

    useEffect(() => {
        const checkSelection = () => {
            if (!elementRef.current) {
                setIsSelected(false);
                return;
            }

            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
                setIsSelected(false);
                return;
            }

            const range = selection.getRangeAt(0);
            const element = elementRef.current;

            // Check if element is within the selection range
            try {
                // Method 1: Check if the element intersects with the selection range
                const elementRange = document.createRange();
                elementRange.selectNodeContents(element);

                // Compare the ranges
                const isWithinSelection = 
                    range.compareBoundaryPoints(Range.START_TO_END, elementRange) > 0 &&
                    range.compareBoundaryPoints(Range.END_TO_START, elementRange) < 0;

                // Method 2: Also check if selection contains the element
                const selectionContainsElement = selection.containsNode(element, true);

                setIsSelected(isWithinSelection || selectionContainsElement);
            } catch (error) {
                // Handle potential errors with range comparison
                setIsSelected(false);
            }
        };

        // Check selection immediately
        checkSelection();

        // Listen for selection changes
        document.addEventListener('selectionchange', checkSelection);
        
        // Also listen for mouse up to catch selection end
        document.addEventListener('mouseup', checkSelection);
        
        // Listen for keyboard selection (Shift+Arrow keys)
        document.addEventListener('keyup', (e) => {
            if (e.shiftKey) {
                checkSelection();
            }
        });

        return () => {
            document.removeEventListener('selectionchange', checkSelection);
            document.removeEventListener('mouseup', checkSelection);
            document.removeEventListener('keyup', checkSelection);
        };
    }, [elementRef]);

    return isSelected;
}

/**
 * Get the selection highlight color from the current theme
 * Returns a Tailwind class for consistent selection styling
 */
export function getSelectionHighlightClass(isSelected: boolean): string {
    if (!isSelected) return '';
    
    // Show only a blue border when selected, no background change
    // This creates a clean visual indication without changing the element's appearance
    return 'ring-2 ring-blue-500';
}