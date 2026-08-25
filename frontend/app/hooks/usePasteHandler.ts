// Hook for handling paste operations in contenteditable elements
// Manages pasted images and large text blocks with configurable thresholds

import { useCallback, useState, RefObject, useRef, useEffect } from 'react';
import {
    PastedContent,
    DEFAULT_LINE_THRESHOLD,
    createInlineImageElement,
    createInlineTextElement,
    insertAtCursor,
    fileToDataURL,
    resizeImage,
    generatePasteId,
    countLines,
    cleanupBlobUrl
} from '~/lib/paste-utils';

export interface UsePasteHandlerOptions {
    lineThreshold?: number;
    maxImageWidth?: number;
    maxImageHeight?: number;
    onPasteImage?: (id: string, dataUrl: string) => Promise<void>;
    onPasteText?: (id: string, text: string) => void;
    onRemoveContent?: (id: string) => void;
}

export function usePasteHandler(
    editorRef: RefObject<HTMLDivElement | null>,
    options: UsePasteHandlerOptions = {}
) {
    const {
        lineThreshold = DEFAULT_LINE_THRESHOLD,
        maxImageWidth = 800,
        maxImageHeight = 600,
        onPasteImage,
        onPasteText,
        onRemoveContent
    } = options;

    const [pastedContent, setPastedContent] = useState<Map<string, PastedContent>>(new Map());
    const blobUrlsRef = useRef<Set<string>>(new Set());

    // Cleanup blob URLs on unmount
    useEffect(() => {
        return () => {
            // eslint-disable-next-line react-hooks/exhaustive-deps
            blobUrlsRef.current.forEach(cleanupBlobUrl);
        };
    }, []);

    const handlePasteImage = useCallback(async (file: File | Blob) => {
        const id = generatePasteId();
        
        // Create initial loading state
        setPastedContent(prev => {
            const newMap = new Map(prev);
            newMap.set(id, {
                id,
                type: 'image',
                isLoading: true,
                progress: 0
            });
            return newMap;
        });

        try {
            // Convert to data URL
            const dataUrl = await fileToDataURL(file);
            
            // Update progress
            setPastedContent(prev => {
                const newMap = new Map(prev);
                const item = newMap.get(id);
                if (item) {
                    item.progress = 30;
                }
                return newMap;
            });

            // Resize if needed
            const resizedDataUrl = await resizeImage(dataUrl, maxImageWidth, maxImageHeight);
            
            // Update progress
            setPastedContent(prev => {
                const newMap = new Map(prev);
                const item = newMap.get(id);
                if (item) {
                    item.progress = 60;
                    item.preview = resizedDataUrl;
                }
                return newMap;
            });

            // Insert into editor
            if (editorRef.current) {
                const element = createInlineImageElement(id, resizedDataUrl);
                insertAtCursor(element, editorRef.current);
                
                // Track blob URL if needed
                if (resizedDataUrl.startsWith('blob:')) {
                    blobUrlsRef.current.add(resizedDataUrl);
                }
                
                // Ensure focus is maintained
                editorRef.current.focus();
                
                // Trigger input event to update state
                editorRef.current.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // Call optional handler for server upload
            if (onPasteImage) {
                await onPasteImage(id, resizedDataUrl);
            }

            // Mark as complete
            setPastedContent(prev => {
                const newMap = new Map(prev);
                const item = newMap.get(id);
                if (item) {
                    item.isLoading = false;
                    item.progress = 100;
                }
                return newMap;
            });

            // Update the element in the editor to remove loading state
            if (editorRef.current) {
                const element = editorRef.current.querySelector(`[data-paste-id="${id}"]`);
                if (element) {
                    element.classList.remove('loading');
                }
            }

        } catch (error) {
            console.error('Error handling pasted image:', error);
            
            // Remove from state on error
            setPastedContent(prev => {
                const newMap = new Map(prev);
                newMap.delete(id);
                return newMap;
            });

            // Remove from editor
            if (editorRef.current) {
                const element = editorRef.current.querySelector(`[data-paste-id="${id}"]`);
                element?.remove();
            }
        }
    }, [editorRef, maxImageWidth, maxImageHeight, onPasteImage]);

    const handlePasteText = useCallback((text: string) => {
        const lines = countLines(text);
        
        if (lines <= lineThreshold) {
            // Let default paste behavior handle small text
            return false;
        }

        const id = generatePasteId();
        
        // Add to state
        setPastedContent(prev => {
            const newMap = new Map(prev);
            newMap.set(id, {
                id,
                type: 'text',
                lineCount: lines,
                content: text
            });
            return newMap;
        });

        // Insert into editor
        if (editorRef.current) {
            const element = createInlineTextElement(id, lines, text);
            insertAtCursor(element, editorRef.current);
            
            // Ensure focus is maintained
            editorRef.current.focus();
            
            // Trigger input event to update state
            editorRef.current.dispatchEvent(new Event('input', { bubbles: true }));
        }

        // Call optional handler
        onPasteText?.(id, text);

        return true; // Indicate we handled the paste
    }, [editorRef, lineThreshold, onPasteText]);

    const handlePaste = useCallback((event: ClipboardEvent) => {
        if (!event.clipboardData) return;

        // Check for images first
        const items = Array.from(event.clipboardData.items);
        const imageItem = items.find(item => item.type.startsWith('image/'));

        if (imageItem) {
            event.preventDefault();
            const file = imageItem.getAsFile();
            if (file) {
                handlePasteImage(file);
            }
            return;
        }

        // Always get plain text to avoid HTML formatting
        const text = event.clipboardData.getData('text/plain');
        if (text) {
            event.preventDefault();

            // Check if it's large text that needs special handling
            if (!handlePasteText(text)) {
                // For regular text, use execCommand for simpler insertion
                // Note: execCommand is deprecated but still the best option because:
                // 1. No standardized replacement exists yet
                // 2. It maintains undo/redo functionality
                // 3. All browsers still support it and won't remove it
                document.execCommand('insertText', false, text);

                // Trigger input event to update state
                editorRef.current?.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }
    }, [handlePasteImage, handlePasteText, editorRef]);

    const removeContent = useCallback((id: string) => {
        // Remove from state first (this will trigger portal cleanup)
        setPastedContent(prev => {
            const newMap = new Map(prev);
            const item = newMap.get(id);
            
            // Cleanup blob URL if needed
            if (item?.preview?.startsWith('blob:')) {
                cleanupBlobUrl(item.preview);
                blobUrlsRef.current.delete(item.preview);
            }
            
            newMap.delete(id);
            return newMap;
        });

        // Much longer delay for DOM removal to ensure React completes cleanup
        // This allows React's reconciliation to fully complete
        setTimeout(() => {
            if (editorRef.current) {
                const element = editorRef.current.querySelector(`[data-paste-id="${id}"]`);
                // Extra safety checks before removal
                if (element && element.parentNode && editorRef.current.contains(element)) {
                    // Check if element still has the same ID (not recycled)
                    if (element.getAttribute('data-paste-id') === id) {
                        // Check for adjacent non-breaking spaces and remove them
                        const nextSibling = element.nextSibling;
                        const prevSibling = element.previousSibling;
                        
                        element.remove();
                        
                        // Clean up adjacent non-breaking spaces
                        if (nextSibling && nextSibling.nodeType === Node.TEXT_NODE && 
                            nextSibling.textContent === '\u00A0') {
                            nextSibling.remove();
                        }
                        if (prevSibling && prevSibling.nodeType === Node.TEXT_NODE && 
                            prevSibling.textContent === '\u00A0') {
                            prevSibling.remove();
                        }
                    }
                }
                
                // Trigger input event to recalculate isEmpty state
                editorRef.current.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }, 200); // Increased delay significantly

        // Call optional handler
        onRemoveContent?.(id);
    }, [editorRef, onRemoveContent]);

    const updateProgress = useCallback((id: string, progress: number) => {
        setPastedContent(prev => {
            const newMap = new Map(prev);
            const item = newMap.get(id);
            if (item) {
                item.progress = progress;
            }
            return newMap;
        });
    }, []);

    const getPastedContent = useCallback(() => {
        return Array.from(pastedContent.values());
    }, [pastedContent]);

    return {
        handlePaste,
        removeContent,
        updateProgress,
        pastedContent: getPastedContent(),
        pastedContentMap: pastedContent
    };
}
