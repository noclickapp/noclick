/*
This is the chatbar/mic component that is the app's main
interaction interface.

TODO: refactor to make much simpler
 - InputBox component that handles message view with mic/file upload etc
 - Header component that handles header bar with context and chat history dropdowns etc
 - Perhaps create a separate folder for these NoClick related components since they are
    unlikely to be generally useful
*/
import { useState, useEffect, useCallback, useMemo, useRef, memo } from 'react';
import { ResizablePanel } from '~/components/ui/ResizablePanel';
import { cn } from '~/lib/utils'; // some tailwind thing
import { KeyHint } from '~/components/shared/KeyHint';
import { ParticlesBackground } from '~/components/utils/ParticlesBackground';
import { useSocketConnection } from '~/hooks/useSocketConnection';
import { useSocketAuthMonitor } from '~/hooks/useSocketAuthMonitor';
import {
    sendEvent,
    sendEventAsync,
    AgentPauseRequest,
} from '~/lib/socket-sender';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import { MessageCircle, Square, Store, ChevronDown, Plus } from 'lucide-react';
import { getDefaultPanelWidth } from '~/lib/constants';
import { MessagesView } from '~/components/chat/MessagesView';
import { ChatBox, type ChatBoxRef } from '~/components/chat/ChatBox';
import {
    getCurrentWorkflowId,
    useEffectiveWorkflowId,
    useEffectiveWorkflowName,
    useActiveWorkflowEditorId,
} from '~/components/workflow/WorkflowContext';
import { getBuilderContext } from '~/lib/builder-context';
import { headlessBuilder } from '~/lib/headless-builder';
import { ChatDrawer, ChatDrawerProvider } from '~/components/chat/drawer';
import { DrawingDrawerBridge } from '~/components/chat/DrawingDrawerBridge';
import { BuilderInputBridge } from '~/components/chat/BuilderInputBridge';
import { getPendingBuilderAsk } from '~/lib/pendingBuilderAsk';
import { ChatHistory } from '~/components/chat/ChatHistory';
import { useSidebarConversation } from '~/hooks/useSidebarConversation';
import { useConversation } from '~/hooks/useConversation';
import {
    dispatchPauseAllActiveGens,
    registerOptimisticGen,
} from '~/lib/activeGenStore';
import { Message } from './types';
import {
    type ChatMessageEvent,
    type ChatTranscriptionEvent,
} from '~/types/socket-events.generated';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { InviteBanner } from '~/components/chat/InviteBanner';
import { InterruptedRunBanner } from '~/components/chat/InterruptedRunBanner';
import { OrgSwitcher } from '~/components/organization/OrgSwitcher';
import { LogoMark } from '~/components/shared/LogoMark';

interface NoClickProps {
    isExpanded: boolean;
    /** Skip the open/close width animation (set when toggled via the "/" key). */
    noAnimation?: boolean;
    onExpandChange: (expanded: boolean) => void;
    onWidthChange?: (width: number) => void;
    onDragChange?: (isDragging: boolean) => void;
    isMobileMode?: boolean;
    userEmail?: string;
    userAvatarUrl?: string;
}

type TabType = 'messages' | 'filesystem' | 'frames' | 'marketplace';

// Static tabs array - defined outside component to prevent recreation on every render
const TABS: Array<{ id: TabType; label: string; icon: typeof MessageCircle }> =
    [
        { id: 'messages', label: 'Chat', icon: MessageCircle },
        // { id: 'filesystem', label: 'Files', icon: FolderOpen },
        // { id: 'frames', label: 'Frames', icon: Square },
        // { id: 'marketplace', label: 'Store', icon: Store },
    ];

// Stable empty callbacks for useAudioRecording
const NOOP = () => {};

// Static style objects to prevent recreation
const CHAT_DRAWER_WRAPPER_STYLE = { marginBottom: '-8px' };
const EMPTY_STYLE = {};

// Static CSS for gray theme override - defined outside component to prevent object recreation on every render
const NO_BLUE_THEME_CSS = `
    .no-blue-theme button:focus {
        outline: none !important;
        box-shadow: none !important;
        border-color: hsl(var(--muted-foreground) / 0.5) !important;
    }

    .no-blue-theme button:focus-visible {
        outline: 2px solid hsl(var(--muted-foreground) / 0.5) !important;
        outline-offset: 2px !important;
        box-shadow: 0 0 0 2px hsl(var(--muted-foreground) / 0.5) !important;
    }

    .no-blue-theme *[data-state="active"],
    .no-blue-theme *[aria-selected="true"],
    .no-blue-theme *.active {
        background-color: hsl(var(--accent)) !important;
        color: hsl(var(--accent-foreground)) !important;
    }

    .no-blue-theme *:focus,
    .no-blue-theme *:focus-within {
        --tw-ring-color: hsl(var(--muted-foreground) / 0.5) !important;
        border-color: hsl(var(--muted-foreground) / 0.5) !important;
    }

    /* Chatbox input: a soft, banner-matching focus border instead of the gray
       theme ring. Higher specificity than the generic *:focus-within rule above so it
       wins regardless of stylesheet order. */
    .no-blue-theme [data-chatbox-input]:focus-within {
        border-color: hsl(var(--foreground) / 0.25) !important;
    }
`;

// Custom Dropdown Component (no shadcn, no blue)
const CustomDropdown = ({
    trigger,
    children,
    isOpen,
    onOpenChange,
    onMouseEnter,
    onMouseLeave,
}: {
    trigger: React.ReactNode;
    children: React.ReactNode;
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    onMouseEnter: () => void;
    onMouseLeave: () => void;
}) => {
    const dropdownRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                dropdownRef.current &&
                !dropdownRef.current.contains(event.target as Node)
            ) {
                onOpenChange(false);
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isOpen, onOpenChange]);

    return (
        <div
            ref={dropdownRef}
            className="relative"
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
        >
            <div
                onClick={() => onOpenChange(!isOpen)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onOpenChange(!isOpen);
                    }
                }}
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                aria-haspopup="true"
            >
                {trigger}
            </div>
            {isOpen && (
                <div className="absolute top-full left-0 mt-0.5 min-w-[160px] bg-popover dark:bg-zinc-800 border border-border dark:border-zinc-700 rounded-md shadow-xl z-50 p-1">
                    {children}
                </div>
            )}
        </div>
    );
};

// Placeholder components for the new tabs

const FramesView = () => (
    <div className="h-full p-4 text-foreground">
        <div className="text-center text-muted-foreground mt-8">
            <Square className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-semibold mb-2">Frames</h3>
            <p className="text-sm">Manage your application frames</p>
        </div>
    </div>
);

const MarketplaceView = () => (
    <div className="h-full p-4 text-foreground">
        <div className="text-center text-muted-foreground mt-8">
            <Store className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-semibold mb-2">Marketplace</h3>
            <p className="text-sm">Discover and install components</p>
        </div>
    </div>
);

// Collapsed rail for the chat sidebar. Hover is tracked in JS (not CSS :hover)
// so the tooltip doesn't flash when the rail appears under a stationary cursor on
// collapse — mouseenter only fires on real pointer movement. The tooltip uses the
// command-palette surface color and is anchored bottom-[50vh] so it lines up at
// the same viewport height as the workspace rail's tooltip (both bars share the
// viewport bottom edge though their tops differ).
function CollapsedChatRail() {
    const [hovered, setHovered] = useState(false);
    return (
        <div
            className={cn(
                'relative z-10 h-full w-full transition-colors',
                hovered && 'bg-foreground/[0.02]'
            )}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
        >
            <div
                className={cn(
                    'pointer-events-none absolute left-full bottom-[50vh] z-50 ml-2 flex translate-y-1/2 items-center gap-2 whitespace-nowrap rounded-md border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-2.5 py-1.5 text-xs text-foreground shadow-xl dark:shadow-black/60 transition-opacity duration-150',
                    hovered ? 'opacity-100' : 'opacity-0'
                )}
            >
                Open chat
                <KeyHint keys={['/']} />
            </div>
        </div>
    );
}

export const NoClick = memo(function NoClick({
    isExpanded,
    noAnimation,
    onExpandChange,
    onWidthChange,
    onDragChange,
    isMobileMode = false,
    userEmail,
    userAvatarUrl,
}: NoClickProps) {
    const [activeTab, setActiveTab] = useState<TabType>('messages');
    const [sidebarWidth, setSidebarWidth] = useState(getDefaultPanelWidth());
    const [dropdownOpen, setDropdownOpen] = useState(false);

    // Sidebar conversation state. The hook takes the active workflow
    // editor id and routes the displayed conv to the right slot:
    //   • workflow mounted → workflow's slot in the per-workflow map
    //     (auto-restored across navigations and refreshes; bootstrapped
    //     from BE the first time a workflow is seen in this session).
    //   • no workflow      → a separate "scratch" slot for standalone
    //     chats (so sending without a workflow doesn't taint a real
    //     workflow's thread).
    // All writers (setConversationId / startFreshConversation /
    // switchToConversation) target the active slot automatically.
    const activeWorkflowEditorId = useActiveWorkflowEditorId();
    const {
        conversationId,
        setConversationId,
        startFreshConversation,
        switchToConversation,
    } = useSidebarConversation(activeWorkflowEditorId);
    // Messages MessagesView renders — composed live from the
    // active-gen store + persisted history. Keyed on the sidebar's
    // current conversationId, which useSidebarConversation routes to
    // the right slot (per-workflow map entry, or scratch) based on
    // whether a workflow is mounted.
    const conversationView = useConversation(conversationId);
    const messages = conversationView.messages;

    const { isConnected, isConnecting } = useSocketConnection();
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    // Monitor for auth-related connection failures and auto-redirect to login
    useSocketAuthMonitor();

    // Log conversation ID changes for debugging
    useEffect(() => {
        console.log('[NoClick] Active conversation ID:', conversationId);
    }, [conversationId]);

    // Refresh-recovery is no longer needed: with <ask/> as a turn boundary,
    // there are no "in-flight" persisted bubbles. A paused conversation's
    // trailing assistant is a complete turn whose pending_ask drives the
    // ask drawer (handled by BuilderInputBridge's messages effect). A
    // streaming run that's interrupted by a refresh just loses its partial
    // text — bounded and acceptable per the architecture decision.
    //
    // Bubbles with isComplete: false only exist within the current page-load
    // session, owned by HeadlessBuilder / useCanvasWorkflowEdit's live
    // response listeners. Cross-session stale-bubble cleanup isn't needed
    // because conversations.events never persists incomplete bubbles.

    // True iff there's an active gen for this workflow — derived directly
    // from the activeGenStore via useConversation. Single source of truth;
    // no derivation from messages, no auto-clear effects.
    const isWaitingForResponse = conversationView.isStreaming;

    // VAD (Voice Activity Detection) removed to improve load times
    // Backend transcription handler preserved for future restoration

    // Calculate how many icons can fit in the available space
    // Each icon is roughly 32px wide with padding, plus we need space for the dropdown
    const availableWidth = sidebarWidth - 200; // Reserve space for logo and controls
    const iconWidth = 32;
    const dropdownWidth = 24;
    const maxPossibleTabs = Math.max(1, Math.floor(availableWidth / iconWidth));

    // If we have more tabs than can fit, always reserve space for dropdown
    // This allows us to show promoted icons from dropdown selections
    const hasOverflow = TABS.length > maxPossibleTabs;
    const maxVisibleTabs = hasOverflow
        ? Math.max(1, Math.floor((availableWidth - dropdownWidth) / iconWidth))
        : TABS.length;

    // Memoize tab ordering - only recalculate when dependencies change
    const { visibleTabs, overflowTabs } = useMemo(() => {
        const baseVisibleTabs = TABS.slice(0, maxVisibleTabs);
        const baseOverflowTabs = TABS.slice(maxVisibleTabs);

        // If active tab is in overflow, promote it to visible and push last visible to overflow
        if (
            hasOverflow &&
            baseOverflowTabs.some((tab) => tab.id === activeTab)
        ) {
            const activeTabData = baseOverflowTabs.find(
                (tab) => tab.id === activeTab
            )!;
            const otherOverflowTabs = baseOverflowTabs.filter(
                (tab) => tab.id !== activeTab
            );
            const lastVisibleTab = baseVisibleTabs[baseVisibleTabs.length - 1];

            return {
                visibleTabs: [...baseVisibleTabs.slice(0, -1), activeTabData],
                overflowTabs: [...otherOverflowTabs, lastVisibleTab],
            };
        }

        return {
            visibleTabs: baseVisibleTabs,
            overflowTabs: baseOverflowTabs,
        };
    }, [maxVisibleTabs, hasOverflow, activeTab]);

    // Memoize sidebar style to prevent object recreation
    const sidebarContentStyle = useMemo(
        () => (isMobileMode ? EMPTY_STYLE : { minWidth: `${sidebarWidth}px` }),
        [isMobileMode, sidebarWidth]
    );

    // Handle dropdown hover with delay
    const dropdownTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    // Workflow editing state — subscribed via useSyncExternalStore in
    // WorkflowContext so we re-render synchronously on canvas mount/unmount
    // (and on headless-builder context updates), without the previous
    // 500ms-polling lag.
    const currentWorkflowId = useEffectiveWorkflowId();
    const currentWorkflowName = useEffectiveWorkflowName();
    // The <ask/> drawer is self-managing: BuilderInputBridge subscribes to
    // useActiveWorkflowEditorId() internally and closes itself when the
    // editor it was attached to unmounts — no plumbing required here.

    // Handle workflow edit submission. Two paths:
    //   • Canvas is mounted → DOM event to FlowCanvas (which owns the live
    //     graph state and pipes events back via builder-edit listeners).
    //   • Canvas is NOT mounted → startEditWithoutWorkflow. The brain
    //     decides whether to list_workflows + edit one or build fresh.
    //
    // We deliberately do NOT fall back to ctx.workflowId from a previous
    // canvas mount — that was the source of "silent edits on a workflow
    // the user can't see" (the user's mental model is "no workflow open,
    // why is something being edited?"). If the user wants to edit a
    // specific workflow without a canvas, they can ask for it by name
    // and the brain will resolve it via list_workflows.
    const handleWorkflowEditSubmit = useCallback(
        async (
            prompt: string,
            conversationIdOverride?: string,
            scope?: { type: 'node'; nodeId: string }
        ) => {
            // If the builder is paused on an <ask/>, a typed message answers the
            // ask (resumes the paused turn) instead of starting a fresh edit turn.
            // BuilderInputBridge owns the ask lifecycle, so we hand the message off
            // to it. effectivePending is editor-matched, so a non-null store entry
            // is always valid for the current editor.
            const pendingAsk = getPendingBuilderAsk();
            if (pendingAsk?.conversationId) {
                document.dispatchEvent(
                    new CustomEvent('noclick:builder:input:submit-message', {
                        detail: { message: prompt },
                    })
                );
                return;
            }

            const ctx = getBuilderContext();

            // Use the override when a caller just minted a new conversationId for
            // this prompt — avoids a stale-closure race where setConversationId(new)
            // + setTimeout(submit) would run submit against the previous closure's
            // conversationId, persisting the builder run under the OLD id and
            // breaking auto-resume on refresh.
            const effectiveConversationId =
                conversationIdOverride || conversationId;

            const canvasWorkflowId = getCurrentWorkflowId();

            // Register an optimistic gen the instant the user submits so the
            // bubble appears immediately. The real active_gen:started from
            // the BE evicts this placeholder (matched by conversation_id;
            // see the listener in activeGenStore).
            registerOptimisticGen({
                workflow_id: canvasWorkflowId || null,
                conversation_id: effectiveConversationId,
                prompt,
            });

            if (ctx.isCanvasMounted && canvasWorkflowId) {
                // Canvas is mounted for a specific workflow → let FlowCanvas drive
                console.log(
                    '[NoClick] Dispatching to FlowCanvas, wfId:',
                    canvasWorkflowId
                );
                document.dispatchEvent(
                    new CustomEvent('noclick:workflow:edit', {
                        detail: {
                            workflowId: canvasWorkflowId,
                            prompt,
                            conversationId: effectiveConversationId,
                            scope,
                        },
                    })
                );
                return;
            }

            // No canvas mounted → headless run. Brain handles workflow selection
            // (list_workflows for edits, fresh graph for create-from-scratch).
            console.log(
                '[NoClick] No canvas mounted — starting headless builder'
            );
            headlessBuilder.startEditWithoutWorkflow(prompt, {
                conversationId: effectiveConversationId,
            });
        },
        [conversationId]
    );

    // Stop every in-flight builder run for this user via the
    // cross-module pause bridge. Why a bridge instead of iterating
    // activeGenStore.gens directly: Vite's dev loader can produce
    // duplicate module instances of activeGenStore, so the React
    // closure here may read from a different proxy than the one the
    // socket listener populated. The bridge dispatches a DOM event
    // that every duplicate listens for.
    const handleWorkflowEditStop = useCallback(() => {
        dispatchPauseAllActiveGens();
        if (conversationId) {
            sendEvent(
                AgentPauseRequest.create({ conversation_id: conversationId })
            );
        }
        if (headlessBuilder.isActive()) {
            headlessBuilder.cancel();
        }
    }, [conversationId]);

    // Listen for workflow edit events from FlowCanvas and update messages/state
    // Listen for plan-limit errors from the agentic builder. Live chat
    // state (text, events, completion) flows through activeGenStore and
    // useConversation directly — the legacy reducer that fanned every
    // edit event into the now-dead chat:messages cache was removed.
    useEffect(() => {
        const handler = (
            event: CustomEvent<{ type: string; error?: string }>
        ) => {
            if (event.detail.type !== 'error') return;
            const err = event.detail.error;
            if (err && isPlanLimitError(err)) setPlanLimitError(err);
        };
        document.addEventListener(
            'noclick:workflow:edit:event',
            handler as EventListener
        );
        return () =>
            document.removeEventListener(
                'noclick:workflow:edit:event',
                handler as EventListener
            );
    }, []);

    const handleDropdownHover = useCallback((isHovering: boolean) => {
        if (dropdownTimeoutRef.current) {
            clearTimeout(dropdownTimeoutRef.current);
            dropdownTimeoutRef.current = null;
        }

        if (isHovering) {
            setDropdownOpen(true);
        } else {
            // Delay closing to allow movement to dropdown content
            dropdownTimeoutRef.current = setTimeout(() => {
                setDropdownOpen(false);
            }, 300);
        }
    }, []);

    // Handle plan-limit errors arriving via the legacy chat:message
    // socket event. Live chat content (text deltas, agentic steps,
    // structured content) flows through activeGenStore and surfaces
    // via useConversation; the legacy reducer that fanned every chunk
    // into the now-dead chat:messages cache was removed.
    const messageHandler = useCallback(
        (data: ChatMessageEvent) => {
            if (data.conversation_id && data.conversation_id !== conversationId)
                return;
            if (data.message && isPlanLimitError(data.message)) {
                setPlanLimitError(data.message);
            }
        },
        [conversationId]
    );

    const transcriptionHandler = useCallback((data: ChatTranscriptionEvent) => {
        console.log('Transcription received:', data.transcription);
        // Note: Voice transcription not currently supported in workflow-edit mode
        // TODO: Add transcription support if needed
    }, []);

    // Use type-safe socket event hooks
    useSocketEvent('chat:message', messageHandler, [messageHandler]);
    useSocketEvent('chat:transcription', transcriptionHandler, [
        transcriptionHandler,
    ]);

    // Memoize tab content to prevent unnecessary re-renders during drag
    const tabContent = useMemo(() => {
        switch (activeTab) {
            case 'messages':
                return (
                    <MessagesView
                        messages={messages}
                        workflowId={currentWorkflowId}
                    />
                );
            case 'frames':
                return <FramesView />;
            case 'marketplace':
                return <MarketplaceView />;
            default:
                return (
                    <MessagesView
                        messages={messages}
                        workflowId={currentWorkflowId}
                    />
                );
        }
    }, [activeTab, messages, currentWorkflowId]);

    // Cleanup dropdown timeout on unmount
    useEffect(() => {
        return () => {
            if (dropdownTimeoutRef.current) {
                clearTimeout(dropdownTimeoutRef.current);
            }
        };
    }, []);

    // External "/clear" command (ChatSlashOptions) routes through the
    // sidebar hook's startFreshConversation so all reset paths are unified.
    // Also dispatches noclick:conversation:clear so useConversation's
    // persisted-history projection resets — without this, MessagesView
    // (which now reads useConversation, not the legacy cache) would
    // keep showing the prior turns after /clear.
    useEffect(() => {
        const clearAll = () => {
            startFreshConversation();
            document.dispatchEvent(
                new CustomEvent('noclick:conversation:clear')
            );
        };
        document.addEventListener('noclick:clear-messages', clearAll);
        return () =>
            document.removeEventListener('noclick:clear-messages', clearAll);
    }, [startFreshConversation]);

    const handleWidthChange = useCallback(
        (width: number) => {
            setSidebarWidth(width);
            onWidthChange?.(width);
        },
        [onWidthChange]
    );

    // ChatHistory dropdown picks a specific conversation. Adopts the
    // id, then refetches the BE persisted form and dispatches
    // noclick:conversation:switch so useConversation re-projects.
    // We refetch rather than reuse the FE Message[] passed by the
    // dropdown — the BE shape is what mapPersistedMessages expects.
    const handleConversationChange = useCallback(
        (newConversationId: string, _newMessages: Message[]) => {
            switchToConversation(newConversationId);
            void (async () => {
                try {
                    const resume = (await sendEventAsync({
                        event_name: 'conversation:resume',
                        session_id: newConversationId,
                    } as never)) as { messages?: unknown[] };
                    document.dispatchEvent(
                        new CustomEvent('noclick:conversation:switch', {
                            detail: {
                                conversationId: newConversationId,
                                messages: resume?.messages || [],
                            },
                        })
                    );
                } catch (err) {
                    console.warn(
                        '[NoClick] conversation switch resume failed',
                        err
                    );
                }
            })();
        },
        [switchToConversation]
    );

    const handleNewConversation = useCallback(() => {
        startFreshConversation();
    }, [startFreshConversation]);

    // Start a fresh conversation on external builder-submit events so the prompt
    // lands as the first user bubble and runs against a clean history.
    // Optimistic gen registration happens inside handleWorkflowEditSubmit;
    // we just mint the id and route the submit through it.
    useEffect(() => {
        const handler = (event: Event) => {
            const detail = (event as CustomEvent<{ prompt?: string }>).detail;
            const prompt = detail?.prompt?.trim();
            if (!prompt) return;
            const newConversationId =
                globalThis.crypto?.randomUUID?.() || Math.random().toString(36);
            setConversationId(newConversationId);
            // Pass the new id explicitly; the callback's closure still
            // holds the previous conversationId.
            setTimeout(
                () => handleWorkflowEditSubmit(prompt, newConversationId),
                0
            );
        };
        document.addEventListener('noclick:builder:submit', handler);
        return () =>
            document.removeEventListener('noclick:builder:submit', handler);
    }, [setConversationId, handleWorkflowEditSubmit]);

    // "Ask AI" buttons (e.g., the execution-error block in FlowHelperView) send
    // a pre-built message into the current conversation — no reset, so the
    // brain keeps prior context. An optional `scope` locks the edit to a single
    // node when sent from the FlowHelper Edit tab (enforced server-side via
    // edit_scope on the builder request). Expand the chat sidebar first (same
    // event FlowCanvasEmptyState fires on submit) so the user sees the builder
    // pick the message up instead of it disappearing into a collapsed sidebar.
    useEffect(() => {
        const handler = (event: Event) => {
            const detail = (
                event as CustomEvent<{
                    message?: string;
                    scope?: { type: 'node'; nodeId: string };
                }>
            ).detail;
            const message = detail?.message?.trim();
            if (!message) return;
            document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
            handleWorkflowEditSubmit(message, undefined, detail?.scope);
        };
        document.addEventListener('noclick:builder:ask', handler);
        return () =>
            document.removeEventListener('noclick:builder:ask', handler);
    }, [handleWorkflowEditSubmit]);

    // Retry an interrupted run (InterruptedRunBanner auto-resume). Re-submits the
    // original prompt as an edit pinned to the DEAD run's conversation, so the
    // backend loads that run's checkpoint (skip the brain + already-built nodes)
    // rather than starting a fresh build on the ambient conversation.
    useEffect(() => {
        const handler = (event: Event) => {
            const detail = (
                event as CustomEvent<{
                    prompt?: string;
                    conversationId?: string;
                }>
            ).detail;
            const prompt = detail?.prompt?.trim();
            if (!prompt) return;
            handleWorkflowEditSubmit(prompt, detail?.conversationId);
        };
        document.addEventListener('noclick:builder:retry', handler);
        return () =>
            document.removeEventListener('noclick:builder:retry', handler);
    }, [handleWorkflowEditSubmit]);

    // Stop button on FlowCanvasEmptyState (and any other surface that wants
    // to halt the in-flight builder run) routes through the same handler the
    // sidebar ChatBox uses — sends agent:pause, cancels the headless builder,
    // marks the in-flight bubble complete.
    useEffect(() => {
        document.addEventListener(
            'noclick:builder:stop',
            handleWorkflowEditStop
        );
        return () =>
            document.removeEventListener(
                'noclick:builder:stop',
                handleWorkflowEditStop
            );
    }, [handleWorkflowEditStop]);

    // When the user pastes an n8n workflow on the canvas, render an n8n-import
    // badge as the "user message" for this conversation. FlowCanvas drives the
    // actual edit via startCanvasEdit — we're purely showing the bubble here so
    // the chat transcript mirrors the on-canvas action.
    useEffect(() => {
        const handler = (event: Event) => {
            const detail = (event as CustomEvent<{ nodeCount?: number }>)
                .detail;
            const nodeCount = detail?.nodeCount;
            if (nodeCount == null) return;
            const newConversationId =
                globalThis.crypto?.randomUUID?.() || Math.random().toString(36);
            setConversationId(newConversationId);
        };
        document.addEventListener('noclick:n8n:import:start', handler);
        return () =>
            document.removeEventListener('noclick:n8n:import:start', handler);
    }, [setConversationId]);

    // Expanded chat interface content (shared between mobile and desktop)
    const expandedContent = (
        <>
            {/* Force Gray Theme - Override any blue colors */}
            <style>{NO_BLUE_THEME_CSS}</style>

            <ParticlesBackground count={250} starOpacity={0.6} />

            {/* Always render chat content to preserve state, hide with CSS when collapsed */}
            <div
                className={
                    isExpanded || isMobileMode
                        ? 'h-full flex flex-col'
                        : 'hidden'
                }
            >
                <ChatDrawerProvider>
                    <DrawingDrawerBridge />
                    <BuilderInputBridge
                        messages={messages}
                        conversationId={conversationId}
                    />

                    <div
                        className={
                            isMobileMode
                                ? 'flex-1 flex flex-col overflow-hidden'
                                : 'h-full overflow-hidden'
                        }
                        data-onboarding="chat"
                    >
                        <div
                            className={
                                isMobileMode
                                    ? 'flex-1 flex flex-col relative z-10 no-blue-theme'
                                    : 'h-full flex flex-col relative z-10 no-blue-theme'
                            }
                            style={sidebarContentStyle}
                        >
                            <div className="p-3 flex justify-between items-center flex-shrink-0">
                                <div className="flex items-center gap-3 min-w-0 flex-1">
                                    {/* Org Switcher / Username Display - fades out when sidebar collapses */}
                                    <div
                                        className={cn(
                                            'transition-all duration-200 ease-out',
                                            isExpanded
                                                ? 'opacity-100 translate-x-0'
                                                : 'opacity-0 -translate-x-2 pointer-events-none'
                                        )}
                                    >
                                        {userEmail ? (
                                            <OrgSwitcher
                                                userEmail={userEmail}
                                                userAvatarUrl={userAvatarUrl}
                                            />
                                        ) : (
                                            <div className="flex items-center gap-2 flex-shrink-0">
                                                <LogoMark className="w-5 h-5" />
                                                <span className="text-sm font-medium text-foreground/80">
                                                    NoClick
                                                </span>
                                            </div>
                                        )}
                                    </div>

                                    <div className="flex items-center gap-0.5 flex-shrink-0">
                                        {/* Chat History and New Chat buttons */}
                                        <ChatHistory
                                            currentConversationId={
                                                conversationId
                                            }
                                            onConversationChange={
                                                handleConversationChange
                                            }
                                        />
                                        <button
                                            onClick={handleNewConversation}
                                            className="flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors duration-200 ml-2"
                                            title="New Chat"
                                            data-onboarding="new-chat"
                                        >
                                            <Plus className="w-5 h-5" />
                                        </button>

                                        {hasOverflow && (
                                            <CustomDropdown
                                                isOpen={dropdownOpen}
                                                onOpenChange={setDropdownOpen}
                                                onMouseEnter={() =>
                                                    handleDropdownHover(true)
                                                }
                                                onMouseLeave={() =>
                                                    handleDropdownHover(false)
                                                }
                                                trigger={
                                                    <button
                                                        className="flex items-center justify-center w-6 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-700/50 transition-all"
                                                        style={{
                                                            outline: 'none',
                                                            boxShadow: 'none',
                                                        }}
                                                        title="More tabs"
                                                    >
                                                        <ChevronDown className="w-3 h-3" />
                                                    </button>
                                                }
                                            >
                                                {overflowTabs.map((tab) => {
                                                    const Icon = tab.icon;
                                                    return (
                                                        <button
                                                            key={tab.id}
                                                            onClick={() => {
                                                                setActiveTab(
                                                                    tab.id
                                                                );
                                                                setDropdownOpen(
                                                                    false
                                                                );
                                                            }}
                                                            className={cn(
                                                                'flex items-center gap-2 px-3 py-2 text-xs w-full text-left hover:bg-accent dark:hover:bg-zinc-700 transition-all rounded-md',
                                                                activeTab ===
                                                                    tab.id
                                                                    ? 'bg-accent dark:bg-zinc-600 text-accent-foreground border-l-2 border-muted-foreground'
                                                                    : 'text-muted-foreground hover:text-foreground'
                                                            )}
                                                            style={{
                                                                outline: 'none',
                                                                boxShadow:
                                                                    'none',
                                                            }}
                                                        >
                                                            <Icon className="w-4 h-4" />
                                                            <span>
                                                                {tab.label}
                                                            </span>
                                                        </button>
                                                    );
                                                })}
                                            </CustomDropdown>
                                        )}
                                    </div>
                                </div>

                                <div className="flex items-center gap-3 flex-shrink-0">
                                    <div
                                        className={cn(
                                            'rounded-full transition-all',
                                            isConnected
                                                ? 'w-2 h-2 bg-foreground'
                                                : isConnecting
                                                  ? 'w-3 h-3 border-2 border-foreground/30 border-t-foreground animate-spin'
                                                  : 'w-2.5 h-2.5 border border-red-600 dark:border-red-400'
                                        )}
                                        title={
                                            isConnected
                                                ? 'Connected to API'
                                                : isConnecting
                                                  ? 'Reconnecting to API...'
                                                  : 'Disconnected from API'
                                        }
                                    />
                                    {!isMobileMode && (
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onExpandChange(false);
                                            }}
                                            className="text-muted-foreground hover:text-foreground"
                                        >
                                            ✕
                                        </button>
                                    )}
                                </div>
                            </div>

                            <div className="flex-1 min-h-0">{tabContent}</div>

                            <div
                                className={
                                    isMobileMode
                                        ? 'relative flex-shrink-0'
                                        : 'relative flex-shrink-0 mt-auto'
                                }
                            >
                                <div className="relative">
                                    <div
                                        className="absolute bottom-full left-0 right-0 h-[35vh] overflow-hidden pointer-events-none"
                                        style={CHAT_DRAWER_WRAPPER_STYLE}
                                        data-onboarding="chat-drawer"
                                    >
                                        <ChatDrawer />
                                    </div>
                                    <div
                                        className="relative z-10 outline-none"
                                        data-onboarding="chat-input"
                                        data-tour-target="chatbox"
                                    >
                                        <InterruptedRunBanner
                                            conversationId={conversationId}
                                        />
                                        <InviteBanner
                                            workflowId={currentWorkflowId}
                                        />
                                        <ChatBox
                                            isWaitingForResponse={
                                                isWaitingForResponse
                                            }
                                            workflowName={currentWorkflowName}
                                            onWorkflowEditSubmit={
                                                handleWorkflowEditSubmit
                                            }
                                            onInterrupt={handleWorkflowEditStop}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </ChatDrawerProvider>
            </div>

            {/* Collapsed state — the whole bar is clickable (ResizablePanel owns the
                onClick that expands it); a subtle hover brighten and a tooltip
                showing the "/" shortcut are the cues that it opens the chat. */}
            <div className={isExpanded || isMobileMode ? 'hidden' : 'h-full'}>
                {!isExpanded && !isMobileMode && <CollapsedChatRail />}
            </div>

            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => {
                    if (!open) setPlanLimitError(null);
                }}
                errorMessage={planLimitError || ''}
            />
        </>
    );

    // Mobile mode: Render expanded content directly without ResizablePanel
    if (isMobileMode) {
        return (
            <div className="flex-1 w-full bg-background text-foreground relative flex flex-col">
                {expandedContent}
            </div>
        );
    }

    // Desktop mode: Wrap with ResizablePanel
    return (
        <ResizablePanel
            isExpanded={isExpanded}
            noAnimation={noAnimation}
            onExpandChange={onExpandChange}
            onWidthChange={handleWidthChange}
            onDragChange={onDragChange}
        >
            {expandedContent}
        </ResizablePanel>
    );
});
