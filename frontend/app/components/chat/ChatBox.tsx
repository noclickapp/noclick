/**
 * ChatBox - AI workflow-edit input component.
 *
 * Features slash commands, drawing/screenshot integration, and context mentions.
 */
import {
    useState,
    useEffect,
    KeyboardEvent,
    useCallback,
    useRef,
    memo,
    forwardRef,
    useImperativeHandle,
} from 'react';
import { cn } from '~/lib/utils';
import { useSocketConnection } from '~/hooks/useSocketConnection';
import { useDrawer } from '~/hooks/useDrawer';
import { ChatSlashOptions } from '~/components/chat/drawer';
import type { Command } from '~/components/chat/drawer/ChatSlashOptions';
import { ChatContextOptions, type ContextOption } from '~/components/chat/drawer/ChatContextOptions';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { SendButton } from './SendButton';
import { EditableInput, type EditableInputRef } from './EditableInput';
import { UsageDrawer } from '~/components/usage/UsageDrawer';
import { DebugDrawer } from '~/components/debug/DebugDrawer';
import { useAnalytics } from '~/lib/analytics';
import type { ContentItem, ImageUrl } from '~/types/socket-schema.generated';
import type { ExtractedContent } from '~/lib/paste-utils';
import { createReferenceChipElement } from '~/components/workflow/referenceChip';
import {
    JSON_FIELD_DRAG_START_EVENT,
    JSON_FIELD_DRAG_END_EVENT,
    type JsonFieldDragDetail,
} from '~/lib/jsonFieldDragBridge';

const IMAGE_DATA_URL_REGEX = /^data:([^;]+);base64,/i;

const extractMimeType = (value: string | undefined | null): string | undefined => {
    if (!value) return undefined;
    const match = IMAGE_DATA_URL_REGEX.exec(value);
    return match?.[1];
};

const normalizeImageContent = (value: ContentItem['image_url']): ImageUrl | null => {
    if (!value) return null;
    if (typeof value === 'string') {
        const format = extractMimeType(value);
        return format ? { url: value, format } : { url: value };
    }
    if (!value.url) {
        return null;
    }
    const format = value.format ?? extractMimeType(value.url);
    return {
        url: value.url,
        ...(value.detail ? { detail: value.detail } : {}),
        ...(format ? { format } : {})
    };
};

const imageContentEquals = (
    a: ContentItem['image_url'],
    b: ContentItem['image_url']
): boolean => {
    const first = normalizeImageContent(a);
    const second = normalizeImageContent(b);
    if (!first && !second) return true;
    if (!first || !second) return false;
    return (
        first.url === second.url &&
        (first.format ?? null) === (second.format ?? null) &&
        (first.detail ?? null) === (second.detail ?? null)
    );
};

interface ChatBoxProps {
    isWaitingForResponse: boolean;
    onInterrupt?: () => void;
    onInteraction?: () => void;
    /** Name of the workflow currently being edited */
    workflowName?: string;
    /** Callback when the user submits an edit prompt */
    onWorkflowEditSubmit?: (prompt: string) => void;
    className?: string;
}

export interface ChatBoxRef {
    appendText: (text: string) => void;
    focus: () => void;
}

// Extend Window interface for global function
declare global {
    interface Window {
        noClickFocusInput?: () => void;
    }
}

// Memoized to prevent unnecessary re-renders during FlowCanvas drag operations
export const ChatBox = memo(forwardRef<ChatBoxRef, ChatBoxProps>((
    {
        isWaitingForResponse,
        onInterrupt,
        onInteraction,
        workflowName,
        onWorkflowEditSubmit,
        className,
    },
    ref
) => {
    // Use shared cached state so input persists across page refreshes and from demo chatbox
    const [inputValue, setInputValue] = useCachedValtioState<string>(
        'chat',
        'draftInput',
        '',
        true // skipRedisSync - no need to sync draft text to Redis
    );
    const [showBorder, setShowBorder] = useState(false);
    const inputRef = useRef<EditableInputRef>(null);
    const [lastContent, setLastContent] = useState<ExtractedContent>({ text: '', attachments: [], items: [] });
    const [isDrawingActive, setIsDrawingActive] = useState(false);

    // Context drawer state for @ mentions
    const [contextQuery, setContextQuery] = useState('');
    const [isContextActive, setIsContextActive] = useState(false);
    const contextRegisteredRef = useRef(false);
    const lastContextStateRef = useRef({ isActive: false, query: '' });
    const lastDrawerQueryRef = useRef('');

    const { isOpen: isDrawerOpen, registerDrawer, unregisterDrawer, updateDrawer, visibleDrawerId } = useDrawer();
    // The agentic builder's <ask/> drawer is up. A typed message answers the
    // ask, so we let the user send even though a drawer is open and hint at it
    // in the placeholder. 'builder-input' is BuilderInputBridge's DRAWER_ID.
    const isBuilderAskOpen = visibleDrawerId === 'builder-input';
    const slashOptionsRegisteredRef = useRef(false);
    const { logActivity } = useAnalytics();

    const { isConnected } = useSocketConnection();

    // Debug panel visibility state - shared with DebugViewer and NavBar
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const [_debugPanelVisible, setDebugPanelVisible] = useCachedValtioState<boolean>(
        'noclick-ui',
        'debugPanelVisible',
        true
    );

    const handleKeyPress = useCallback(
        (e: KeyboardEvent<HTMLDivElement>) => {
            // Handle Escape key
            if (e.key === 'Escape') {
                if (isDrawerOpen) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (visibleDrawerId) {
                        unregisterDrawer(visibleDrawerId);
                    }
                    // Clear "/" if it's the only character
                    if (inputValue === '/') {
                        setInputValue('');
                        if (inputRef.current) {
                            inputRef.current.clear();
                        }
                    }
                }
                return;
            }
            
            // Handle Enter key
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (inputRef.current) {
                    const content = inputRef.current.getContent();
                    const hasText = content.text.trim().length > 0;
                    const hasImages = content.items.some(
                        item => item.type === 'image_url' && normalizeImageContent(item.image_url)
                    );

                    // Allow sending if no drawer is open, if it's the drawing
                    // drawer, or if the builder is paused on an <ask/> (the
                    // message answers the ask).
                    const isDrawingDrawer = visibleDrawerId === 'drawing-options';
                    const canSend = !isDrawerOpen || isDrawingDrawer || isBuilderAskOpen;

                    if ((hasText || hasImages) && !isWaitingForResponse && canSend) {
                        // If drawing drawer is open, close it first
                        if (isDrawingDrawer) {
                            document.dispatchEvent(new CustomEvent('noclick:drawing-close'));
                            unregisterDrawer('drawing-options');
                        }

                        // Turn off inspect mode when sending message
                        document.dispatchEvent(new CustomEvent('noclick:inspector-off'));

                        onWorkflowEditSubmit?.(content.text.trim());
                        inputRef.current.clear();
                        setInputValue('');
                        setLastContent({ text: '', attachments: [], items: [] });
                    }
                }
            }
        },
        [inputValue, isDrawerOpen, isWaitingForResponse, setInputValue, unregisterDrawer, visibleDrawerId, onWorkflowEditSubmit, isBuilderAskOpen]
    );

    const handleSendClick = useCallback(() => {
        if (isWaitingForResponse && onInterrupt) {
            onInterrupt();
            return;
        }

        if (inputRef.current) {
            const content = inputRef.current.getContent();
            const hasText = content.text.trim().length > 0;
            const hasImages = content.items.some(
                item => item.type === 'image_url' && normalizeImageContent(item.image_url)
            );
            if ((hasText || hasImages) && !isWaitingForResponse) {
                // If drawing drawer is open, close it first
                if (visibleDrawerId === 'drawing-options') {
                    document.dispatchEvent(new CustomEvent('noclick:drawing-close'));
                    unregisterDrawer('drawing-options');
                }

                // Turn off inspect mode when sending message
                document.dispatchEvent(new CustomEvent('noclick:inspector-off'));

                onWorkflowEditSubmit?.(content.text.trim());
                inputRef.current.clear();
                setInputValue('');
                setLastContent({ text: '', attachments: [], items: [] });
            }
        }
    }, [isWaitingForResponse, onInterrupt, visibleDrawerId, setInputValue, unregisterDrawer, onWorkflowEditSubmit]);

    // Helper to trigger interaction callback
    const triggerInteraction = useCallback(() => {
        onInteraction?.();
    }, [onInteraction]);

    // Manage ChatSlashOptions drawer registration
    const shouldShowSlashOptions = inputValue === '/' || inputValue.startsWith('/');
    
    useEffect(() => {
        if (shouldShowSlashOptions) {
            const content = (
                <ChatSlashOptions
                    inputValue={inputValue}
                    onCommandSelect={(command: Command) => {
                        // Handle /usage command specially
                        if (command.id === 'usage') {
                            // First, close the slash options drawer
                            unregisterDrawer('slash-options');
                            slashOptionsRegisteredRef.current = false;

                            registerDrawer(
                                'usage-dashboard',
                                <UsageDrawer
                                    onClose={() => {
                                        unregisterDrawer('usage-dashboard');
                                    }}
                                    onNavigateToDashboard={() => {
                                        // Close the drawer first
                                        unregisterDrawer('usage-dashboard');
                                          // Wait a tick for drawer to close, then navigate to settings tab with usage section
                                          setTimeout(() => {
                                              window.dispatchEvent(new CustomEvent('noclick:switch-tab', {
                                                  detail: {
                                                      tab: 'settings',
                                                      section: 'usage'
                                                  },
                                                  bubbles: true
                                              }));
                                          }, 50);
                                    }}
                                />
                            );
                        }

                        // Handle /debug command specially
                        if (command.id === 'debug') {
                            // First, close the slash options drawer
                            unregisterDrawer('slash-options');
                            slashOptionsRegisteredRef.current = false;

                            // Make debug panel visible again (in case it was hidden)
                            // Update valtio state for persistence
                            setDebugPanelVisible(true);
                            // Dispatch event for immediate cross-component update (valtio subscription may not fire due to proxy reference changes)
                            window.dispatchEvent(new CustomEvent('noclick:debug-panel-show'));

                            registerDrawer(
                                'debug-dashboard',
                                <DebugDrawer
                                    onClose={() => {
                                        unregisterDrawer('debug-dashboard');
                                    }}
                                    onNavigateToDashboard={() => {
                                        // Close the drawer first
                                        unregisterDrawer('debug-dashboard');
                                        // Wait a tick for drawer to close, then dispatch event to switch to debug tab
                                        setTimeout(() => {
                                            window.dispatchEvent(new CustomEvent('noclick:switch-tab', {
                                                detail: { tab: 'debug' },
                                                bubbles: true
                                            }));
                                        }, 50);
                                    }}
                                />,
                                { resizable: true }
                            );
                        }

                        // Clear the input immediately when a command is selected
                        setInputValue('');
                        // Also clear the EditableInput component directly
                        if (inputRef.current) {
                            inputRef.current.clear();
                        }
                    }}
                    onInputChange={(value) => {
                        setInputValue(value);
                    }}
                    onClose={() => {
                        unregisterDrawer('slash-options');
                        slashOptionsRegisteredRef.current = false;
                        setInputValue(''); // Clear input when drawer closes
                        inputRef.current?.focus();
                    }}
                />
            );
            
            if (!slashOptionsRegisteredRef.current) {
                // First time showing - register with new timestamp
                logActivity('slash_options_drawer_opened', {
                    initial_input: inputValue
                });
                registerDrawer('slash-options', content);
                slashOptionsRegisteredRef.current = true;
            } else {
                // Already registered - just update content without changing timestamp
                updateDrawer('slash-options', content);
            }
        } else {
            // Unregister when no longer needed
            if (slashOptionsRegisteredRef.current) {
                unregisterDrawer('slash-options');
                slashOptionsRegisteredRef.current = false;
            }
        }
    }, [shouldShowSlashOptions, inputValue, registerDrawer, unregisterDrawer, updateDrawer]);

    // Detect @ pattern for context drawer
    useEffect(() => {
        // Don't show context drawer if slash options are showing
        if (shouldShowSlashOptions) {
            if (lastContextStateRef.current.isActive || lastContextStateRef.current.query) {
                lastContextStateRef.current = { isActive: false, query: '' };
                setIsContextActive(false);
                setContextQuery('');
            }
            return;
        }

        const { isActive, query } = detectContextTrigger(inputValue);

        // Only update state if values actually changed
        if (isActive !== lastContextStateRef.current.isActive || query !== lastContextStateRef.current.query) {
            lastContextStateRef.current = { isActive, query };
            setIsContextActive(isActive);
            setContextQuery(query);
        }
    }, [inputValue, shouldShowSlashOptions]);

    // Manage ChatContextOptions drawer registration
    useEffect(() => {
        if (isContextActive) {
            // Only create content and update if query changed
            if (!contextRegisteredRef.current || lastDrawerQueryRef.current !== contextQuery) {
                lastDrawerQueryRef.current = contextQuery;

                const content = (
                    <ChatContextOptions
                        query={contextQuery}
                        onContextSelect={(option: ContextOption) => {
                            // Calculate replace length (@ symbol + query)
                            const replaceLength = contextQuery.length + 1; // +1 for @

                            // Insert context tag at cursor, replacing @query
                            if (inputRef.current) {
                                inputRef.current.insertContextTag(option.value, replaceLength);
                            }

                            // Close drawer
                            unregisterDrawer('context-options');
                            contextRegisteredRef.current = false;
                            lastDrawerQueryRef.current = '';
                            setIsContextActive(false);
                            setContextQuery('');

                            // Log analytics
                            logActivity('context_inserted', {
                                option_id: option.id,
                                option_label: option.label,
                                query: contextQuery
                            });
                        }}
                        onClose={() => {
                            unregisterDrawer('context-options');
                            contextRegisteredRef.current = false;
                            lastDrawerQueryRef.current = '';
                            setIsContextActive(false);
                            setContextQuery('');
                        }}
                    />
                );

                if (!contextRegisteredRef.current) {
                    // First time showing - register with new timestamp
                    logActivity('context_drawer_opened', {
                        initial_query: contextQuery
                    });
                    registerDrawer('context-options', content);
                    contextRegisteredRef.current = true;
                } else {
                    // Already registered - update content when query changes
                    updateDrawer('context-options', content);
                }
            }
        } else {
            // Unregister when no longer needed
            if (contextRegisteredRef.current) {
                unregisterDrawer('context-options');
                contextRegisteredRef.current = false;
                lastDrawerQueryRef.current = '';
            }
        }
    }, [isContextActive, contextQuery, registerDrawer, unregisterDrawer, updateDrawer, logActivity]);

    // Handle input value updates from EditableInput
    const handleInputChange = useCallback((value: string) => {
        triggerInteraction();
        setInputValue(value);
    }, [triggerInteraction]);

    const handleContentChange = useCallback((content: ExtractedContent) => {
        setLastContent(prev => {
            if (
                prev.text === content.text &&
                prev.items.length === content.items.length &&
                prev.items.every((item, index) => {
                    const next = content.items[index];
                    if (!next || item.type !== next.type) {
                        return false;
                    }
                    if (item.type === 'text') {
                        return (item.text ?? '') === (next.text ?? '');
                    }
                    return imageContentEquals(item.image_url, next.image_url);
                })
            ) {
                return prev;
            }
            return content;
        });
    }, []);

    // Detect @ pattern for context mentions
    const detectContextTrigger = useCallback((input: string): { isActive: boolean; query: string } => {
        // Get cursor position from the contenteditable div
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || !inputRef.current) {
            return { isActive: false, query: '' };
        }

        // For simplicity, we'll use the input string length as cursor position
        // In a contenteditable div, this approximates cursor position for our use case
        const cursorPos = input.length;

        // Find last @ before cursor
        const beforeCursor = input.slice(0, cursorPos);
        const lastAtIndex = beforeCursor.lastIndexOf('@');

        if (lastAtIndex === -1) {
            return { isActive: false, query: '' };
        }

        // Check character before @ - only trigger if it's nothing (start) or whitespace
        if (lastAtIndex > 0) {
            const charBeforeAt = beforeCursor[lastAtIndex - 1];
            // If there's a non-whitespace character before @, don't trigger
            if (charBeforeAt && !/\s/.test(charBeforeAt)) {
                return { isActive: false, query: '' };
            }
        }

        // Get text after @ until cursor
        const afterAt = beforeCursor.slice(lastAtIndex + 1);

        // Check if there's a space after @ (which closes context)
        if (afterAt.includes(' ')) {
            return { isActive: false, query: '' };
        }

        // Active if @ is at word boundary
        return { isActive: true, query: afterAt };
    }, []);

    // Handle border fade-in/out effect with immediate state updates
    useEffect(() => {
        const hasText = lastContent.text.trim().length > 0;
        const hasImages = lastContent.items.some(
            item => item.type === 'image_url' && normalizeImageContent(item.image_url)
        );
        setShowBorder(hasText || hasImages);
    }, [lastContent]);



    // Expose methods to parent component
    useImperativeHandle(ref, () => ({
        appendText: (text: string) => {
            if (inputRef.current) {
                // Get current value and append the new text
                const currentValue = inputRef.current.getValue();
                const newValue = currentValue ? `${currentValue} ${text}` : text;
                inputRef.current.setValue(newValue);
                setInputValue(newValue);

                // Trigger content change to update the send button state
                const content = inputRef.current.getContent();
                handleContentChange(content);

                // Focus the input and move cursor to end
                inputRef.current.focus();

                // Move cursor to the end of the text
                const editableDiv = document.querySelector('[contenteditable="true"]') as HTMLDivElement;
                if (editableDiv) {
                    const range = document.createRange();
                    const selection = window.getSelection();
                    range.selectNodeContents(editableDiv);
                    range.collapse(false); // false = collapse to end
                    selection?.removeAllRanges();
                    selection?.addRange(range);
                }
            }
        },
        focus: () => {
            if (inputRef.current) {
                inputRef.current.focus();
            }
        }
    }), [handleContentChange]);

    // Expose focus method globally
    useEffect(() => {
        window.noClickFocusInput = () => {
            if (inputRef.current) {
                inputRef.current.focus();
            }
        };

        return () => {
            delete window.noClickFocusInput;
        };
    }, []);

    // Show notification when agent finishes and tab is hidden
    const wasWaitingRef = useRef(false);

    useEffect(() => {
        // Track when waiting starts
        if (isWaitingForResponse) {
            wasWaitingRef.current = true;
            return;
        }

        // Agent just finished responding (transition from true → false)
        if (wasWaitingRef.current && !isWaitingForResponse) {
            wasWaitingRef.current = false;

            // Only notify if tab is hidden
            if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
                try {
                    const notification = new Notification('NoClick', {
                        body: 'Your response is ready',
                        icon: '/logo-notification.svg',
                        requireInteraction: false // Auto-dismiss
                    });

                    // Focus tab when notification is clicked
                    notification.onclick = () => {
                        window.focus();
                        notification.close();
                    };
                } catch (error) {
                    console.error('[Notification] Failed to create notification:', error);
                }
            }
        }
    }, [isWaitingForResponse]);

    // Track drawing state changes from ViteViewer
    useEffect(() => {
        const handleDrawingStateChange = (event: Event) => {
            const customEvent = event as CustomEvent;
            const { isDrawing } = customEvent.detail;
            setIsDrawingActive(isDrawing);
            console.log('[ChatBox] Drawing state changed:', isDrawing);
        };

        document.addEventListener('noclick:drawing-state-changed', handleDrawingStateChange);
        return () => {
            document.removeEventListener('noclick:drawing-state-changed', handleDrawingStateChange);
        };
    }, []);

    // Listen for drawing events and handle drawing tag insertion/updates
    useEffect(() => {
        const handleDrawingStarted = () => {
            // Only insert drawing tag if drawing tool is actually active
            if (!isDrawingActive) {
                console.log('[ChatBox] Drawing started event received but drawing tool is not active, ignoring');
                return;
            }

            // Drawing started for the first time - insert initial tag with placeholder
            console.log('[ChatBox] Drawing started, inserting initial tag');
            if (inputRef.current) {
                // Insert with a placeholder screenshot that will be updated soon
                const placeholderScreenshot = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
                inputRef.current.insertDrawingTag(placeholderScreenshot);
            }
        };

        const handleDrawingCleared = () => {
            // Drawing has been cleared - remove the drawing tag
            if (inputRef.current) {
                inputRef.current.removeDrawingTag();
            }
        };

        const handleDrawingScreenshot = (event: MessageEvent) => {
            if (event.data?.type === 'noclick-screenshot-response' &&
                event.data.success &&
                event.data.screenshot) {
                // Only update drawing tag if drawing is active
                if (!isDrawingActive) {
                    console.log('[ChatBox] Screenshot received but drawing tool is not active, ignoring');
                    return;
                }

                // Screenshot received - update existing drawing tag
                if (inputRef.current) {
                    inputRef.current.updateDrawingScreenshot(event.data.screenshot);
                }
            }
        };

        document.addEventListener('noclick:drawing-started', handleDrawingStarted);
        document.addEventListener('noclick:drawing-cleared', handleDrawingCleared);
        window.addEventListener('message', handleDrawingScreenshot);

        return () => {
            document.removeEventListener('noclick:drawing-started', handleDrawingStarted);
            document.removeEventListener('noclick:drawing-cleared', handleDrawingCleared);
            window.removeEventListener('message', handleDrawingScreenshot);
        };
    }, [isDrawingActive])

    // Listen for element selection events from inspector
    useEffect(() => {
        const handleElementSelected = (event: Event) => {
            const customEvent = event as CustomEvent;
            const { tagName, noclickId, html } = customEvent.detail;
            console.log('[ChatBox] Element selected:', { tagName, noclickId, html: html?.substring(0, 100) });

            // Insert HTML element tag at cursor position
            if (inputRef.current) {
                inputRef.current.insertHtmlElementTag(tagName, noclickId, html || '');
                console.log('[ChatBox] Inserted HTML element tag:', tagName, noclickId);
            }
        };

        document.addEventListener('noclick:element-selected', handleElementSelected);

        return () => {
            document.removeEventListener('noclick:element-selected', handleElementSelected);
        };
    }, [])


    const hasSendableContent = lastContent.text.trim().length > 0 ||
        lastContent.items.some(item => item.type === 'image_url' && normalizeImageContent(item.image_url));

    // JSON-field drag bridge — see jsonFieldDragBridge.ts. ChatBox sits in a
    // sibling tree from FlowCanvas's DndContext, so it can't `useDroppable`;
    // we mirror the drag through document events and land the drop here.
    //
    // The pointer listeners attach ONCE at mount and are gated by the
    // `activeDragRef` closure — fast drags fire pointerup within one render
    // of the drag-start event, so deferring attachment until React re-renders
    // would race past them.
    //
    // `lastCursorRangeRef` preserves the caret position the user left in the
    // editor. The drag steals focus from the contenteditable; without
    // restoring the saved Range on drop, `focus()` would land the caret at
    // position 0 and every drop would become a prefix.
    const chatBoxContainerRef = useRef<HTMLDivElement>(null);
    const activeDragRef = useRef<JsonFieldDragDetail | null>(null);
    const lastCursorRangeRef = useRef<Range | null>(null);
    const [isJsonFieldDragActive, setIsJsonFieldDragActive] = useState(false);
    const [isJsonFieldDragOver, setIsJsonFieldDragOver] = useState(false);

    // Track the editor caret on user-driven interactions only. Document-level
    // `selectionchange` is too broad — it also fires when the user clicks the
    // draggable JSON field in the InputPanel, at which point the browser can
    // momentarily place a position-0 range inside the now-defocused editor.
    // Capturing that range would clobber the typed cursor we need on drop.
    useEffect(() => {
        const editableEl = chatBoxContainerRef.current?.querySelector('[contenteditable="true"]');
        if (!editableEl) return;
        const captureRange = () => {
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) return;
            const range = selection.getRangeAt(0);
            if (editableEl.contains(range.commonAncestorContainer)) {
                lastCursorRangeRef.current = range.cloneRange();
            }
        };
        editableEl.addEventListener('keyup', captureRange);
        editableEl.addEventListener('mouseup', captureRange);
        editableEl.addEventListener('input', captureRange);
        return () => {
            editableEl.removeEventListener('keyup', captureRange);
            editableEl.removeEventListener('mouseup', captureRange);
            editableEl.removeEventListener('input', captureRange);
        };
    }, []);

    useEffect(() => {
        const isInside = (x: number, y: number) => {
            const rect = chatBoxContainerRef.current?.getBoundingClientRect();
            if (!rect) return false;
            return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
        };

        const handleStart = (e: Event) => {
            const detail = (e as CustomEvent<JsonFieldDragDetail>).detail;
            if (detail && typeof detail.nodeId === 'string' && typeof detail.path === 'string') {
                activeDragRef.current = { nodeId: detail.nodeId, path: detail.path, displayValue: detail.displayValue };
                setIsJsonFieldDragActive(true);
            }
        };
        const handleEnd = () => {
            activeDragRef.current = null;
            setIsJsonFieldDragActive(false);
            setIsJsonFieldDragOver(false);
        };
        const handlePointerMove = (e: PointerEvent) => {
            if (!activeDragRef.current) return;
            setIsJsonFieldDragOver(isInside(e.clientX, e.clientY));
        };
        const handlePointerUp = (e: PointerEvent) => {
            const drag = activeDragRef.current;
            if (!drag) return;
            if (!isInside(e.clientX, e.clientY)) return;
            // Clear synchronously — the dnd-kit drag-end fires its own DOM
            // event right after, and we don't want a second insertion path.
            activeDragRef.current = null;
            const reference = `{{${drag.nodeId}.${drag.path}}}`;
            const editableEl = chatBoxContainerRef.current?.querySelector<HTMLElement>('[contenteditable="true"]');
            if (!editableEl || !inputRef.current) return;

            // Snapshot the saved range BEFORE focus(). focus() on a
            // contenteditable creates a synthetic position-0 selection and
            // can fire a synchronous selectionchange; reading the ref after
            // focus would clobber the user's caret with the start of editor.
            const saved = lastCursorRangeRef.current;
            const savedIsValid = !!(saved && editableEl.contains(saved.commonAncestorContainer));

            editableEl.focus();
            const selection = window.getSelection();
            if (selection) {
                selection.removeAllRanges();
                if (savedIsValid && saved) {
                    selection.addRange(saved);
                } else {
                    const endRange = document.createRange();
                    endRange.selectNodeContents(editableEl);
                    endRange.collapse(false);
                    selection.addRange(endRange);
                }
            }
            inputRef.current.insertElementAtCursor(createReferenceChipElement(reference));
        };

        document.addEventListener(JSON_FIELD_DRAG_START_EVENT, handleStart);
        document.addEventListener(JSON_FIELD_DRAG_END_EVENT, handleEnd);
        document.addEventListener('pointermove', handlePointerMove);
        document.addEventListener('pointerup', handlePointerUp);
        return () => {
            document.removeEventListener(JSON_FIELD_DRAG_START_EVENT, handleStart);
            document.removeEventListener(JSON_FIELD_DRAG_END_EVENT, handleEnd);
            document.removeEventListener('pointermove', handlePointerMove);
            document.removeEventListener('pointerup', handlePointerUp);
        };
    }, []);

    const showJsonFieldDropHint = isJsonFieldDragActive && isJsonFieldDragOver;

    return (
        <div ref={chatBoxContainerRef} className={cn("p-2 relative", className)}>
            {/* Main ChatBox - sits on top of the drawer */}
            <div data-chatbox-input className="relative bg-card backdrop-blur-sm rounded-xl border border-input dark:border-zinc-600/50 pt-2 px-2 pb-1">
                {/* Main text input area */}
                <div className="flex gap-3 items-start mb-1">
                    <EditableInput
                        ref={inputRef}
                        placeholder={
                            isConnected
                                ? isBuilderAskOpen
                                    ? 'Reply to continue, or use the form above'
                                    : 'Describe workflow edits (/ for commands)'
                                : 'Connecting...'
                        }
                        disabled={!isConnected || isWaitingForResponse}
                        className="flex-1"
                        value={inputValue}
                        onChange={handleInputChange}
                        onContentChange={handleContentChange}
                        onKeyDown={handleKeyPress}
                        maxHeight={window.innerHeight * 0.7}
                    />
                </div>

                {/* Bottom row with workflow label and action buttons */}
                <div className="flex items-center justify-between mt-1">
                    <div className="flex items-center gap-0 mt-0.5">
                        <div className="flex items-center gap-2 min-w-0">
                            <span className="text-xs text-muted-foreground dark:text-zinc-500 truncate max-w-[200px] pl-1">
                                {workflowName ? `Editing: ${workflowName}` : 'Open a workflow to start editing'}
                            </span>
                        </div>
                    </div>

                    {/* Action buttons */}
                    <div className="flex items-center gap-1.5 -mr-0.5 mb-px">
                        <SendButton
                            onClick={handleSendClick}
                            hasContent={hasSendableContent}
                            isWaitingForResponse={isWaitingForResponse}
                            showBorder={showBorder}
                            onInterrupt={onInterrupt}
                        />
                    </div>
                </div>
                {showJsonFieldDropHint && (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl bg-card/95 border-2 border-dashed border-muted-foreground/60 dark:border-zinc-500/60">
                        <span className="text-xs text-foreground font-medium">Drop to insert reference</span>
                    </div>
                )}
            </div>
        </div>
    );
}));

ChatBox.displayName = 'ChatBox'; 
