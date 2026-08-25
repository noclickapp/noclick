// Hook for managing inline drawing screenshot content in contenteditable elements
// Provides auto-insertion and update capabilities for drawing screenshots

import { useCallback, useState, RefObject, useRef } from 'react';
import {
    PastedContent,
    createInlineDrawingElement,
    insertAtCursor,
    generatePasteId
} from '~/lib/paste-utils';

const DRAWING_ID_PREFIX = 'drawing-';

export interface UseDrawingHandlerOptions {
    onRemoveContent?: (id: string) => void;
}

export function useDrawingHandler(
    editorRef: RefObject<HTMLDivElement | null>,
    options: UseDrawingHandlerOptions = {}
) {
    const { onRemoveContent } = options;

    const [drawingContent, setDrawingContent] = useState<Map<string, PastedContent>>(new Map());
    const isInsertingRef = useRef(false);

    // Insert a new drawing tag at cursor position
    const insertDrawingTag = useCallback((screenshot: string) => {
        // Prevent concurrent insertions
        if (isInsertingRef.current) {
            console.log('[Drawing Handler] Insert already in progress, skipping...');
            return '';
        }
        
        isInsertingRef.current = true;
        
        try {
            const id = `${DRAWING_ID_PREFIX}${generatePasteId()}`;
            
            // Remove any existing drawing tag first (only one drawing at a time)
            const existingDrawingId = Array.from(drawingContent.keys()).find(key => 
                key.startsWith(DRAWING_ID_PREFIX)
            );
            if (existingDrawingId) {
                console.log('[Drawing Handler] Removing existing drawing before inserting new one:', existingDrawingId);
                removeDrawingTag(existingDrawingId);
            }

        // Create new drawing content
        setDrawingContent(prev => {
            const newMap = new Map(prev);
            newMap.set(id, {
                id,
                type: 'drawing',
                preview: screenshot,
                isUpdating: false
            });
            return newMap;
        });

        // Insert into editor
        if (editorRef.current) {
            const element = createInlineDrawingElement(id, screenshot);
            insertAtCursor(element, editorRef.current);
            
            console.log('[Drawing Handler] Inserted drawing tag at cursor:', id);
        }

            return id;
        } finally {
            isInsertingRef.current = false;
        }
    }, [drawingContent, editorRef]);

    // Update existing drawing screenshot
    const updateDrawingScreenshot = useCallback((screenshot: string) => {
        const existingDrawingId = Array.from(drawingContent.keys()).find(key => 
            key.startsWith(DRAWING_ID_PREFIX)
        );

        if (!existingDrawingId) {
            // No existing drawing, insert new one
            return insertDrawingTag(screenshot);
        }

        // Update the screenshot and mark as updating
        setDrawingContent(prev => {
            const newMap = new Map(prev);
            const item = newMap.get(existingDrawingId);
            if (item) {
                item.preview = screenshot;
                item.isUpdating = true;
            }
            return newMap;
        });

        // Update DOM element
        if (editorRef.current) {
            const element = editorRef.current.querySelector(`[data-drawing-id="${existingDrawingId}"]`) as HTMLElement;
            if (element) {
                element.dataset.drawingScreenshot = screenshot;
            }
        }

        // Clear updating state after a short delay
        setTimeout(() => {
            setDrawingContent(prev => {
                const newMap = new Map(prev);
                const item = newMap.get(existingDrawingId);
                if (item) {
                    item.isUpdating = false;
                }
                return newMap;
            });
        }, 300);

        console.log('[Drawing Handler] Updated drawing screenshot:', existingDrawingId);
        return existingDrawingId;
    }, [drawingContent, editorRef, insertDrawingTag]);

    // Remove drawing tag
    const removeDrawingTag = useCallback((id?: string) => {
        let targetId = id;
        
        if (!targetId) {
            // Find the drawing ID if not provided
            targetId = Array.from(drawingContent.keys()).find(key => 
                key.startsWith(DRAWING_ID_PREFIX)
            );
        }

        if (!targetId) return;

        // Remove from state
        setDrawingContent(prev => {
            const newMap = new Map(prev);
            newMap.delete(targetId!);
            return newMap;
        });

        // Remove from DOM
        if (editorRef.current) {
            const element = editorRef.current.querySelector(`[data-drawing-id="${targetId}"]`);
            if (element) {
                // Remove the element and any adjacent non-breaking spaces
                const nextSibling = element.nextSibling;
                if (nextSibling && nextSibling.nodeType === Node.TEXT_NODE && nextSibling.textContent === '\u00A0') {
                    nextSibling.remove();
                }
                element.remove();
            }
        }

        // Notify parent if callback provided
        onRemoveContent?.(targetId);
        
        console.log('[Drawing Handler] Removed drawing tag:', targetId);
    }, [drawingContent, editorRef, onRemoveContent]);

    // Get current drawing ID
    const getCurrentDrawingId = useCallback(() => {
        return Array.from(drawingContent.keys()).find(key => 
            key.startsWith(DRAWING_ID_PREFIX)
        );
    }, [drawingContent]);

    // Check if has drawing content
    const hasDrawingContent = useCallback(() => {
        return drawingContent.size > 0;
    }, [drawingContent]);

    return {
        drawingContentMap: drawingContent,
        insertDrawingTag,
        updateDrawingScreenshot,
        removeDrawingTag,
        getCurrentDrawingId,
        hasDrawingContent
    };
}