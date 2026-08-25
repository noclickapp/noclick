// EditableInput component - a contenteditable div that supports inline paste tags
// Replaces textarea to enable rich content while maintaining text input functionality

import {
    forwardRef,
    useImperativeHandle,
    useRef,
    useEffect,
    useState,
    KeyboardEvent,
    useCallback,
    ReactNode,
    useMemo
} from 'react';
import { cn } from '~/lib/utils';
import { usePasteHandler } from '~/hooks/usePasteHandler';
import { useDrawingHandler } from '~/hooks/useDrawingHandler';
import { useHtmlElementHandler, type HtmlElementContent } from '~/hooks/useHtmlElementHandler';
import { useContextHandler, type ContextContent } from '~/hooks/useContextHandler';
import { InlineImageTag, InlineTextTag } from './paste';
import { InlineDrawingTag } from './paste/InlineDrawingTag';
import { InlineHtmlTag } from './paste/InlineHtmlTag';
import { InlineContextTag } from './paste/InlineContextTag';
import { extractContent, insertAtCursor, type ExtractedContent, type PastedContent } from '~/lib/paste-utils';
import { createPortal } from 'react-dom';

export interface EditableInputRef {
    focus: () => void;
    blur: () => void;
    clear: () => void;
    getValue: () => string;
    getContent: () => ExtractedContent;
    setValue: (value: string) => void;
    insertDrawingTag: (screenshot: string) => string;
    updateDrawingScreenshot: (screenshot: string) => string;
    removeDrawingTag: (id?: string) => void;
    insertHtmlElementTag: (tagName: string, noclickId: string, html: string) => string;
    removeHtmlElementTag: (id?: string) => void;
    insertTextAtCursor: (text: string, replaceLength?: number) => void;
    insertElementAtCursor: (element: HTMLElement) => void;
    insertContextTag: (value: string, replaceLength?: number) => string;
    removeContextTag: (id?: string) => void;
}

export interface EditableInputProps {
    placeholder?: string;
    disabled?: boolean;
    className?: string;
    value?: string;
    onChange?: (value: string) => void;
    onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void;
    onPaste?: (e: React.ClipboardEvent<HTMLDivElement>) => void;
    lineThreshold?: number;
    maxImageWidth?: number;
    maxImageHeight?: number;
    onPasteImage?: (id: string, dataUrl: string) => Promise<void>;
    onPasteText?: (id: string, text: string) => void;
    autoFocus?: boolean;
    maxHeight?: number;
    onContentChange?: (content: ExtractedContent) => void;
}

export const EditableInput = forwardRef<EditableInputRef, EditableInputProps>(
    (
        {
            placeholder = 'Type a message...',
            disabled = false,
            className,
            value = '',
            onChange,
            onKeyDown,
            onPaste: onPasteCustom,
            lineThreshold = 10,
            maxImageWidth,
            maxImageHeight,
            onPasteImage,
            onPasteText,
            autoFocus = false,
            maxHeight = 200,
            onContentChange
        },
        ref
    ) => {
        const editorRef = useRef<HTMLDivElement>(null);
        const [isEmpty, setIsEmpty] = useState(true);
        const [tagPortals, setTagPortals] = useState<Map<string, ReactNode>>(new Map());
        const lastValueRef = useRef(value);

        const {
            handlePaste,
            removeContent,
            pastedContentMap
        } = usePasteHandler(editorRef, {
            lineThreshold,
            maxImageWidth,
            maxImageHeight,
            onPasteImage,
            onPasteText
        });

        const {
            drawingContentMap,
            insertDrawingTag,
            updateDrawingScreenshot,
            removeDrawingTag
        } = useDrawingHandler(editorRef, {
            onRemoveContent: removeContent
        });

        const {
            htmlElementContentMap,
            insertHtmlElementTag,
            removeHtmlElementTag
        } = useHtmlElementHandler(editorRef, {
            onRemoveContent: removeContent
        });

        const {
            contextContentMap,
            insertContextTag,
            removeContextTag
        } = useContextHandler(editorRef, {
            onRemoveContent: removeContent
        });

        // Combine pasted, drawing, HTML element, and context content maps - memoized to prevent infinite loops
        const allContentMap = useMemo(() => {
            const combined = new Map<string, PastedContent | HtmlElementContent | ContextContent>();
            for (const contentMap of [pastedContentMap, drawingContentMap, htmlElementContentMap]) {
                contentMap.forEach((content, id) => combined.set(id, content));
            }
            contextContentMap.forEach((content, id) => combined.set(id, content));
            return combined;
        }, [pastedContentMap, drawingContentMap, htmlElementContentMap, contextContentMap]);

        // Update tag portals when pasted or drawing content changes
        useEffect(() => {
            const newPortals = new Map<string, ReactNode>();

            allContentMap.forEach((content) => {
                if (content.type === 'text' && 'tagName' in content) {
                    // HTML element tags also use the text discriminator, so
                    // handle their more specific shape before pasted text.
                    const htmlElement = editorRef.current?.querySelector(`[data-html-element-id="${content.id}"]`);
                    if (htmlElement && htmlElement instanceof HTMLElement && htmlElement.parentNode) {
                        if (content.html && htmlElement.dataset) {
                            htmlElement.dataset.htmlElementContent = content.html;
                        }
                        newPortals.set(
                            content.id,
                            createPortal(
                                <InlineHtmlTag
                                    id={content.id}
                                    tagName={content.tagName}
                                    noclickId={content.noclickId}
                                    onRemove={removeHtmlElementTag}
                                    onHover={(noclickId) => {
                                        document.dispatchEvent(new CustomEvent('noclick:highlight-element', {
                                            detail: { noclickId }
                                        }));
                                    }}
                                    onMouseLeave={() => {
                                        document.dispatchEvent(new CustomEvent('noclick:unhighlight-element'));
                                    }}
                                />,
                                htmlElement
                            )
                        );
                    }
                    return;
                }

                const element = editorRef.current?.querySelector(`[data-paste-id="${content.id}"]`);
                if (element && element instanceof HTMLElement && element.parentNode) {
                    if (content.type === 'image') {
                        newPortals.set(
                            content.id,
                            createPortal(
                                <InlineImageTag
                                    id={content.id}
                                    preview={content.preview || ''}
                                    isLoading={content.isLoading}
                                    progress={content.progress}
                                    onRemove={removeContent}
                                />,
                                element
                            )
                        );
                    } else if (content.type === 'text') {
                        newPortals.set(
                            content.id,
                            createPortal(
                                <InlineTextTag
                                    id={content.id}
                                    lineCount={content.lineCount || 0}
                                    content={content.content || ''}
                                    onRemove={removeContent}
                                />,
                                element
                            )
                        );
                    }
                } else if (content.type === 'drawing') {
                    const drawingElement = editorRef.current?.querySelector(`[data-drawing-id="${content.id}"]`);
                    if (drawingElement && drawingElement instanceof HTMLElement && drawingElement.parentNode) {
                        newPortals.set(
                            content.id,
                            createPortal(
                                <InlineDrawingTag
                                    id={content.id}
                                    screenshot={content.preview || ''}
                                    isUpdating={content.isUpdating}
                                    onRemove={removeDrawingTag}
                                    onClick={() => {
                                        console.log('[EditableInput] Drawing tag clicked, opening drawer');
                                        // Dispatch event to open drawing (not toggle, so it won't close if already open)
                                        document.dispatchEvent(new CustomEvent('noclick:open-drawing'));
                                    }}
                                />,
                                drawingElement
                            )
                        );
                    }
                } else if (content.type === 'context') {
                    // Context tags
                    const contextElement = editorRef.current?.querySelector(`[data-context-id="${content.id}"]`);
                    if (contextElement && contextElement instanceof HTMLElement && contextElement.parentNode) {
                        newPortals.set(
                            content.id,
                            createPortal(
                                <InlineContextTag
                                    id={content.id}
                                    value={content.value}
                                    onRemove={removeContextTag}
                                />,
                                contextElement
                            )
                        );
                    }
                }
            });

            setTagPortals(newPortals);
            
            // Update isEmpty state when content changes
            if (editorRef.current) {
                const activePasteIds = new Set(allContentMap.keys());
                const extracted = extractContent(editorRef.current, activePasteIds);
                onContentChange?.(extracted);
                const { text } = extracted;
                
                // More robust empty detection
                const rawContent = editorRef.current.innerHTML.trim();
                
                // Common patterns of "empty" content that browsers might leave
                const emptyPatterns = [
                    /^$/,                                    // Completely empty
                    /^<br\s*\/?>$/i,                        // Just a BR tag
                    /^<div><\/div>$/i,                      // Empty div
                    /^<p><\/p>$/i,                           // Empty paragraph
                    /^[\s\n\r]+$/,                          // Only whitespace/newlines
                    /^(<br\s*\/?>|<div><\/div>|<p><\/p>|[\s\n\r])+$/i  // Combination of above
                ];
                
                const isRawEmpty = emptyPatterns.some(pattern => pattern.test(rawContent));
                const cleanText = text.replace(/[\s\u00A0\u2000-\u200B\u2028\u2029]/g, '').trim();
                
                // Empty if no clean text AND (no content OR raw is empty)
                const isEmpty = cleanText.length === 0 && (allContentMap.size === 0 || isRawEmpty);
                
                setIsEmpty(isEmpty);
            }
        }, [onContentChange, allContentMap]);

        // Handle input changes
        const handleInput = useCallback(() => {
            if (!editorRef.current) return;
            
            const activePasteIds = new Set(allContentMap.keys());
            const extracted = extractContent(editorRef.current, activePasteIds);
            onContentChange?.(extracted);
            const { text } = extracted;
            
            // More robust empty detection
            const rawContent = editorRef.current.innerHTML.trim();
            
            // Common patterns of "empty" content that browsers might leave
            const emptyPatterns = [
                /^$/,                                    // Completely empty
                /^<br\s*\/?>$/i,                        // Just a BR tag
                /^<div><\/div>$/i,                      // Empty div
                /^<p><\/p>$/i,                           // Empty paragraph
                /^[\s\n\r]+$/,                          // Only whitespace/newlines
                /^(<br\s*\/?>|<div><\/div>|<p><\/p>|[\s\n\r])+$/i  // Combination of above
            ];
            
            const isRawEmpty = emptyPatterns.some(pattern => pattern.test(rawContent));
            const cleanText = text.replace(/[\s\u00A0\u2000-\u200B\u2028\u2029]/g, '').trim();
            
            // Empty if no clean text AND (no content OR raw is empty)
            const isEmpty = cleanText.length === 0 && (allContentMap.size === 0 || isRawEmpty);
            
            setIsEmpty(isEmpty);
            
            if (text !== lastValueRef.current) {
                lastValueRef.current = text;
                onChange?.(text);
            }
        }, [onChange, onContentChange, allContentMap]);

        // Handle key events
        const handleKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
            // Forward the event to parent
            onKeyDown?.(e);
            
            // Handle Enter key for single line behavior (unless Shift is pressed)
            if (e.key === 'Enter' && !e.shiftKey) {
                // Parent will handle sending
                return;
            }
            
            // Handle backspace/delete for tags
            if (e.key === 'Backspace' || e.key === 'Delete') {
                const selection = window.getSelection();
                if (!selection || selection.rangeCount === 0) return;
                
                const range = selection.getRangeAt(0);
                
                // Check if we're at a tag boundary
                const container = range.commonAncestorContainer;
                const parentEl = container.nodeType === Node.TEXT_NODE 
                    ? container.parentElement 
                    : container as HTMLElement;
                    
                // Only remove if it's actually a pasted element we're tracking
                if (parentEl?.dataset?.pasteId && allContentMap.has(parentEl.dataset.pasteId)) {
                    e.preventDefault();
                    removeContent(parentEl.dataset.pasteId);
                }
            }
        }, [onKeyDown, removeContent, allContentMap]);

        // Handle paste events
        const handlePasteWrapper = useCallback((e: React.ClipboardEvent<HTMLDivElement>) => {
            // Call custom handler first if provided
            onPasteCustom?.(e);
            
            // If not prevented, use our handler
            if (!e.defaultPrevented) {
                handlePaste(e.nativeEvent);
            }
        }, [handlePaste, onPasteCustom]);

        // Expose methods via ref
        useImperativeHandle(
            ref,
            () => ({
                focus: () => editorRef.current?.focus(),
                blur: () => editorRef.current?.blur(),
                clear: () => {
                    if (editorRef.current) {
                        // First, clear portals from React state
                        setTagPortals(new Map());
                        
                        // Clear all content from state
                        const idsToRemove = Array.from(allContentMap.keys());
                        idsToRemove.forEach(id => removeContent(id));
                        
                        // Immediately clear the DOM content
                        editorRef.current.innerHTML = '';
                        
                        // Force immediate empty state
                        setIsEmpty(true);
                        onChange?.('');
                        onContentChange?.({ text: '', attachments: [], items: [] });
                        
                        // Double-check after React updates in case of race conditions
                        setTimeout(() => {
                            if (editorRef.current && editorRef.current.innerHTML !== '') {
                                editorRef.current.innerHTML = '';
                                setIsEmpty(true);
                            }
                        }, 100);
                    }
                },
                getValue: () => {
                    if (!editorRef.current) return '';
                    const activePasteIds = new Set(allContentMap.keys());
                    const { text } = extractContent(editorRef.current, activePasteIds);
                    return text;
                },
                getContent: () => {
                    if (!editorRef.current) return { text: '', attachments: [], items: [] };
                    const activePasteIds = new Set(allContentMap.keys());
                    return extractContent(editorRef.current, activePasteIds);
                },
                insertDrawingTag,
                updateDrawingScreenshot,
                removeDrawingTag,
                insertHtmlElementTag,
                removeHtmlElementTag,
                insertContextTag,
                removeContextTag,
                setValue: (newValue: string) => {
                    if (editorRef.current) {
                        // Clear only text nodes, preserve pasted elements
                        const childNodes = Array.from(editorRef.current.childNodes);
                        childNodes.forEach(node => {
                            if (node.nodeType === Node.TEXT_NODE) {
                                node.remove();
                            }
                        });
                        // Add new text at the beginning
                        if (newValue) {
                            const textNode = document.createTextNode(newValue);
                            if (editorRef.current.firstChild) {
                                editorRef.current.insertBefore(textNode, editorRef.current.firstChild);
                            } else {
                                editorRef.current.appendChild(textNode);
                            }
                        }
                        // Update empty state considering both text and content elements
                        // Clean non-breaking spaces for proper empty detection
                        const cleanedValue = newValue.replace(/[\u00A0\u2000-\u200B\u2028\u2029]/g, ' ').trim();
                        const hasContent = cleanedValue.length > 0 || allContentMap.size > 0;
                        setIsEmpty(!hasContent);
                        onChange?.(newValue);
                        const activePasteIds = new Set(allContentMap.keys());
                        const extracted = extractContent(editorRef.current, activePasteIds);
                        onContentChange?.(extracted);
                    }
                },
                insertTextAtCursor: (text: string, replaceLength: number = 0) => {
                    if (!editorRef.current) return;

                    const selection = window.getSelection();
                    if (!selection || selection.rangeCount === 0) return;

                    const range = selection.getRangeAt(0);

                    // If replaceLength is provided, delete that many characters before cursor
                    if (replaceLength > 0) {
                        // Move start of range backwards by replaceLength
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

                    // Insert new text
                    const textNode = document.createTextNode(text);
                    range.insertNode(textNode);

                    // Move cursor to after inserted text
                    range.setStartAfter(textNode);
                    range.setEndAfter(textNode);
                    selection.removeAllRanges();
                    selection.addRange(range);

                    // Trigger change events
                    handleInput();
                },
                insertElementAtCursor: (element: HTMLElement) => {
                    // Generic counterpart to insertTextAtCursor for inline
                    // atomic tags (contenteditable=false). Delegates to the
                    // shared `insertAtCursor` so reference chips get the same
                    // trailing-NBSP escape hatch as paste/drawing tags —
                    // without it, the caret would be trapped between the
                    // atomic chip and the end of the editor.
                    if (!editorRef.current) return;
                    insertAtCursor(element, editorRef.current);
                    handleInput();
                }
            }),
            [onChange, onContentChange, allContentMap, removeContent, insertDrawingTag, updateDrawingScreenshot, removeDrawingTag, insertHtmlElementTag, removeHtmlElementTag, insertContextTag, removeContextTag, handleInput]
        );

        // Set initial value only once on mount
        useEffect(() => {
            if (editorRef.current && value) {
                // Only set initial value if the editor is truly empty (no children)
                if (editorRef.current.childNodes.length === 0 && allContentMap.size === 0) {
                    editorRef.current.textContent = value;
                    setIsEmpty(value.trim().length === 0);
                    lastValueRef.current = value;
                }
            } else if (editorRef.current && !value) {
                // If no initial value, make sure placeholder shows
                setIsEmpty(true);
            }
        // eslint-disable-next-line react-hooks/exhaustive-deps
        }, []); // Intentionally empty - only run on mount

        // Handle external value changes (e.g., from cached state loading after mount)
        // Only sync if the value is different from what we last sent via onChange
        useEffect(() => {
            if (editorRef.current && value !== lastValueRef.current) {
                // This is an external change - sync it to the editor
                // Only update if the editor doesn't have rich content (paste tags, etc.)
                if (allContentMap.size === 0) {
                    editorRef.current.textContent = value;
                    setIsEmpty(value.trim().length === 0);
                    lastValueRef.current = value;
                }
            }
        }, [value, allContentMap.size]);

        // Auto-focus
        useEffect(() => {
            if (autoFocus && editorRef.current) {
                editorRef.current.focus();
            }
        }, [autoFocus]);
        
        // Cleanup on unmount
        useEffect(() => {
            return () => {
                // Clear all portals when component unmounts
                setTagPortals(new Map());
            };
        }, []);

        // Auto-resize based on content and monitor for empty state
        useEffect(() => {
            if (!editorRef.current) return;

            const updateHeight = () => {
                const editor = editorRef.current;
                if (!editor) return;

                // Reset height to auto to get natural height
                editor.style.height = 'auto';

                // Set to scrollHeight but cap at maxHeight
                // Ensure minimum height of 32px for consistent initial appearance
                const naturalHeight = editor.scrollHeight;
                const minHeight = 32; // Minimum height to prevent size jump
                const newHeight = Math.min(Math.max(naturalHeight, minHeight), maxHeight);
                editor.style.height = `${newHeight}px`;
            };
            
            const checkEmptyState = () => {
                const editor = editorRef.current;
                if (!editor) return;
                
                // Additional check for empty state when DOM changes
                const activePasteIds = new Set(allContentMap.keys());
                const { text } = extractContent(editor, activePasteIds);
                const rawContent = editor.innerHTML;
                const hasOnlyWhitespaceAndEmptyTags = /^(\s|<br\s*\/?>|<div><\/div>|<p><\/p>)*$/i.test(rawContent);
                const cleanText = text.replace(/\s+/g, '').trim();
                const hasContent = (cleanText.length > 0 || allContentMap.size > 0) && !hasOnlyWhitespaceAndEmptyTags;
                
                setIsEmpty(!hasContent);
            };
            
            const handleChanges = () => {
                updateHeight();
                checkEmptyState();
            };
            
            handleChanges();
            
            // Update on input and DOM mutations
            const observer = new MutationObserver(handleChanges);
            observer.observe(editorRef.current, {
                childList: true,
                subtree: true,
                characterData: true
            });
            
            return () => observer.disconnect();
        }, [maxHeight, allContentMap]);

        return (
            <>
                <div
                    ref={editorRef}
                    contentEditable={!disabled}
                    className={cn(
                        'bg-transparent border-none text-foreground text-sm',
                        'px-0 py-1 min-h-[32px] resize-none',  // Consistent min-height with updateHeight function
                        'focus-visible:ring-0 focus-visible:ring-offset-0 focus:outline-none',
                        'overflow-y-auto overflow-x-visible whitespace-pre-wrap break-words scrollbar-subtle',  // Allow x-overflow for buttons
                        isEmpty && 'empty',
                        disabled && 'opacity-50 cursor-not-allowed',
                        className
                    )}
                    role="textbox"
                    aria-multiline="true"
                    aria-placeholder={placeholder}
                    aria-disabled={disabled}
                    tabIndex={0}
                    data-placeholder={placeholder}
                    onInput={handleInput}
                    onKeyDown={handleKeyDown}
                    onPaste={handlePasteWrapper}
                    suppressContentEditableWarning
                    style={{
                        maxHeight: `${maxHeight}px`,
                        marginRight: '-2px'
                    }}
                />
                {/* Render React components into the pasted elements */}
                {Array.from(tagPortals.values())}
                <style>{`
                    .empty:before {
                        content: attr(data-placeholder);
                        color: hsl(var(--muted-foreground));
                        pointer-events: none;
                        position: absolute;
                    }
                    
                    /* Ensure inline tags can't be edited */
                    [contenteditable="true"] [contenteditable="false"] {
                        user-select: none;
                        cursor: default;
                    }
                `}</style>
            </>
        );
    }
);

EditableInput.displayName = 'EditableInput';
