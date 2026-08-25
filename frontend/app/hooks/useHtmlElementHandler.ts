// Hook for managing inline HTML element tags in contenteditable elements
// Provides insertion and removal capabilities for selected HTML elements

import { useCallback, useState, RefObject } from 'react';
import {
    PastedContent,
    createInlineHtmlElement,
    insertAtCursor,
    generatePasteId
} from '~/lib/paste-utils';

const HTML_ELEMENT_ID_PREFIX = 'html-element-';

export interface HtmlElementContent extends PastedContent {
    type: 'text';
    tagName: string;
    noclickId: string;
    html: string;
}

export interface UseHtmlElementHandlerOptions {
    onRemoveContent?: (id: string) => void;
}

export function useHtmlElementHandler(
    editorRef: RefObject<HTMLDivElement | null>,
    options: UseHtmlElementHandlerOptions = {}
) {
    const { onRemoveContent } = options;

    const [htmlElementContent, setHtmlElementContent] = useState<Map<string, HtmlElementContent>>(new Map());

    // Insert a new HTML element tag at cursor position
    const insertHtmlElementTag = useCallback((tagName: string, noclickId: string, html: string) => {
        const id = `${HTML_ELEMENT_ID_PREFIX}${generatePasteId()}`;

        // Create new HTML element content
        setHtmlElementContent(prev => {
            const newMap = new Map(prev);
            newMap.set(id, {
                id,
                type: 'text', // Use 'text' type since HTML elements are represented as text
                tagName,
                noclickId,
                html
            });
            return newMap;
        });

        // Insert into editor
        if (editorRef.current) {
            const element = createInlineHtmlElement(id, tagName, noclickId, html);
            insertAtCursor(element, editorRef.current);

            console.log('[HTML Element Handler] Inserted HTML element tag at cursor:', id, tagName);
        }

        return id;
    }, [editorRef]);

    // Remove HTML element tag
    const removeHtmlElementTag = useCallback((id?: string) => {
        if (!id) {
            // Remove all HTML element tags if no ID specified
            const htmlElementIds = Array.from(htmlElementContent.keys());
            htmlElementIds.forEach(elementId => removeHtmlElementTag(elementId));
            return;
        }

        // Remove from state
        setHtmlElementContent(prev => {
            const newMap = new Map(prev);
            newMap.delete(id);
            return newMap;
        });

        // Remove from DOM
        if (editorRef.current) {
            const element = editorRef.current.querySelector(`[data-html-element-id="${id}"]`);
            if (element) {
                element.remove();
                console.log('[HTML Element Handler] Removed HTML element tag:', id);
            }
        }

        // Call the onRemoveContent callback if provided
        onRemoveContent?.(id);
    }, [htmlElementContent, editorRef, onRemoveContent]);

    return {
        htmlElementContentMap: htmlElementContent,
        insertHtmlElementTag,
        removeHtmlElementTag
    };
}
