// Hook for managing context tag insertion in ChatBox and removal in EditableInput
// Handles @mention-style context tags with inline rendering

import { useState, useCallback, RefObject } from 'react';
import { createInlineContextElement, generatePasteId } from '~/lib/paste-utils';

export interface ContextContent {
    id: string;
    type: 'context';
    value: string;
}

interface UseContextHandlerOptions {
    onRemoveContent: (id: string) => void;
}

const CONTEXT_ID_PREFIX = 'context-';

export function useContextHandler(
    editorRef: RefObject<HTMLDivElement | null>,
    options: UseContextHandlerOptions
) {
    const [contextContentMap, setContextContentMap] = useState<Map<string, ContextContent>>(new Map());

    const insertContextTag = useCallback((value: string, replaceLength: number = 0): string => {
        const id = `${CONTEXT_ID_PREFIX}${generatePasteId()}`;

        // Store in content map
        setContextContentMap(prev => {
            const newMap = new Map(prev);
            newMap.set(id, {
                id,
                type: 'context',
                value
            });
            return newMap;
        });

        // Insert into editor
        if (editorRef.current) {
            const element = createInlineContextElement(id, value);

            // Handle insertion with replacement
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) {
                editorRef.current.appendChild(element);
                const space = document.createTextNode('\u00A0');
                editorRef.current.appendChild(space);
                return id;
            }

            const range = selection.getRangeAt(0);

            // If replaceLength is provided, delete that many characters before cursor
            if (replaceLength > 0) {
                const startContainer = range.startContainer;
                const startOffset = range.startOffset;

                if (startContainer.nodeType === Node.TEXT_NODE) {
                    const textNode = startContainer as Text;
                    const newOffset = Math.max(0, startOffset - replaceLength);
                    range.setStart(textNode, newOffset);
                }
            }

            // Delete the selected/replaced content
            range.deleteContents();

            // Create a document fragment to insert both element and space together
            const fragment = document.createDocumentFragment();
            fragment.appendChild(element);
            const space = document.createTextNode('\u00A0'); // Non-breaking space
            fragment.appendChild(space);

            // Insert the fragment
            range.insertNode(fragment);

            // Create new range positioned after the space
            const newRange = document.createRange();
            newRange.setStartAfter(space);
            newRange.setEndAfter(space);
            newRange.collapse(true);

            // Update selection
            selection.removeAllRanges();
            selection.addRange(newRange);

            console.log('[Context Handler] Inserted context tag at cursor:', id, value);
        }

        return id;
    }, [editorRef]);

    const removeContextTag = useCallback((id?: string) => {
        if (!editorRef.current) return;

        if (id) {
            // Remove specific tag
            const element = editorRef.current.querySelector(`[data-context-id="${id}"]`);
            if (element) {
                element.remove();
            }
            setContextContentMap(prev => {
                const newMap = new Map(prev);
                newMap.delete(id);
                return newMap;
            });
            options.onRemoveContent(id);
        } else {
            // Remove all context tags
            const elements = editorRef.current.querySelectorAll('[data-context-id]');
            elements.forEach(el => el.remove());
            const ids = Array.from(contextContentMap.keys());
            setContextContentMap(new Map());
            ids.forEach(id => options.onRemoveContent(id));
        }
    }, [editorRef, contextContentMap, options]);

    return {
        contextContentMap,
        insertContextTag,
        removeContextTag
    };
}
