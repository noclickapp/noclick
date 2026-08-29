import { useRef, useEffect, useMemo, useCallback, memo, useState } from 'react';
import { cn } from '~/lib/utils';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { AgenticStepView } from './AgenticStepView';
import { Message, EditSegment } from './types';
import { WorkflowEditEventView } from './WorkflowEditEventView';
import { useAgenticSteps } from './useAgenticSteps';
import { useAgenticAnimations } from './useAgenticAnimations';
import { useStickToBottom } from '~/hooks/useStickToBottom';
// Lazy markdown renderer — keeps react-markdown/katex/Prism/mermaid (~514KB gz)
// off the dashboard's eager eval path; warmed on idle (see effect below).
import { MarkdownRenderer, preloadMarkdownRenderer } from './MarkdownRendererLazy';
import { MessageContentRenderer } from './MessageContentRenderer';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { N8nImportBadge } from '~/components/workflow/N8nImportBadge';
import { useN8nImportStatus } from '~/hooks/useN8nImportStatus';
import { MessageBubble } from './MessageBubble';
import { BuilderProgress } from './BuilderProgress';

// Expandable list of tool call / thinking steps taken during an edit.
// Open by default during streaming, auto-collapses on completion.
const EditStepsView = memo(function EditStepsView({ steps, isComplete }: { steps: string[]; isComplete: boolean }) {
    const [userToggled, setUserToggled] = useState(false);
    const [isOpen, setIsOpen] = useState(false);

    // Auto-collapse when edit completes (unless user manually toggled)
    useEffect(() => {
        if (isComplete && !userToggled) setIsOpen(false);
    }, [isComplete, userToggled]);

    const toggle = () => {
        setUserToggled(true);
        setIsOpen(o => !o);
    };

    return (
        <div className="mb-2">
            <button
                onClick={toggle}
                className="group flex items-center gap-2 text-xs text-foreground/40 hover:text-foreground/60 transition-colors py-0.5"
            >
                <ChevronRight className={cn(
                    "w-3 h-3 text-foreground/20 group-hover:text-foreground/40 transition-transform duration-200",
                    isOpen && "rotate-90"
                )} />
                <span>{steps.length} step{steps.length !== 1 ? 's' : ''}</span>
            </button>
            {isOpen && (
                <div className="mt-1 ml-1.5 pl-3 border-l border-border dark:border-white/[0.06] space-y-px">
                    {steps.map((step, i) => {
                        const isCurrent = !isComplete && i === steps.length - 1;
                        return (
                            <div key={i} className={cn(
                                "text-xs py-0.5 transition-colors",
                                isCurrent ? "text-foreground/50" : "text-foreground/20",
                            )}>
                                {step}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
});

// Collapsible "Reasoning" toggle used while the agent is still streaming.
// Defaults to collapsed because the live status shimmer at the bottom of the
// bubble already conveys progress — the full step list is opt-in.
function StreamingReasoning({ stepCount, children }: { stepCount: number; children: React.ReactNode }) {
    const [isOpen, setIsOpen] = useState(false);
    return (
        <div>
            <button
                onClick={() => setIsOpen(o => !o)}
                className="flex items-center gap-2 py-1 text-xs text-muted-foreground hover:text-foreground/80 transition-colors w-full"
            >
                {isOpen ? (
                    <ChevronDown className="w-3 h-3 transition-transform duration-150" />
                ) : (
                    <ChevronRight className="w-3 h-3 transition-transform duration-150" />
                )}
                <span>Reasoning ({stepCount} step{stepCount !== 1 ? 's' : ''})</span>
            </button>
            {isOpen && (
                <div className="pt-1 pl-2 pr-4">
                    {children}
                </div>
            )}
        </div>
    );
}


interface MessagesViewProps {
    messages: Message[];
    workflowId?: string;
}

// Component for drawing tags with hover preview using Radix UI Tooltip for position awareness
const DrawingTagWithHover = ({ drawingData }: { drawingData: string }) => {
    return (
        <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
                {/* Drawing tag */}
                <div className="flex items-center gap-2 bg-foreground/10 text-foreground border border-foreground/30 rounded-lg px-2.5 py-1.5 my-1 cursor-pointer transition-all hover:bg-foreground/20">
                    {/* Small preview thumbnail */}
                    <img
                        src={drawingData}
                        alt="Drawing"
                        className="w-8 h-8 rounded object-cover bg-black/50"
                    />
                    <span className="text-sm font-medium text-foreground/90">
                        Drawing
                    </span>
                </div>
            </TooltipTrigger>
            <TooltipContent
                side="top"
                align="center"
                className="p-0 bg-card border-border dark:border-zinc-700 max-w-sm !z-[99999]"
                sideOffset={8}
                collisionPadding={16}
                avoidCollisions={true}
                collisionBoundary={typeof window !== 'undefined' ? window.document.documentElement : undefined}
            >
                <div className="p-2">
                    <img
                        src={drawingData}
                        alt="Drawing Preview"
                        className="max-w-xs max-h-64 object-contain rounded"
                    />
                    <div className="mt-1 text-xs text-muted-foreground text-center">
                        Drawing
                    </div>
                </div>
            </TooltipContent>
        </Tooltip>
    );
};

const LoadingComponent = () => (
    <div
        className="w-[250px] h-[150px] rounded-lg border border-border dark:border-white/10 bg-muted relative overflow-hidden"
    >
        <div
            className="absolute inset-0"
            style={{
                background:
                    'linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.05) 50%, transparent 100%)',
                backgroundSize: '200% 100%',
                animation: 'gradient-move 1.5s ease-in-out infinite',
            }}
        />
    </div>
);

function MessagesViewComponent({ messages, workflowId }: MessagesViewProps) {
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Warm the lazy markdown renderer once the main thread is idle (after the
    // dashboard's interactive window), so message markdown is ready without the
    // chunk ever sitting on the eager TTI path.
    useEffect(() => {
        const w = window as unknown as { requestIdleCallback?: (cb: () => void) => number };
        if (w.requestIdleCallback) w.requestIdleCallback(() => preloadMarkdownRenderer());
        else setTimeout(preloadMarkdownRenderer, 300);
    }, []);

    // Track whether an n8n import is still in flight so older-but-still-
    // processing badges get the spinner; once the edit completes the badge
    // freezes on the final node count without the spinner. Must be included
    // in the messageElements useMemo deps below so the bubble badge re-renders
    // when the import completes.
    const n8nImport = useN8nImportStatus();

    // Use custom hooks for agentic step management
    const {
        collapsedReasoning,
        handleToggleExpand,
        handleToggleReasoning: baseHandleToggleReasoning,
        updateStepsWithExpansion,
        calculateMaxHeight,
    } = useAgenticSteps(messages);
    
    const {
        hiddenFromLayout,
        animatingWidths,
        messageRefs,
        startCollapseAnimation,
    } = useAgenticAnimations();
    
    // Combined handler that coordinates both state and animation
    const handleToggleReasoning = useCallback((messageIndex: number) => {
        const isCurrentlyCollapsed = collapsedReasoning[messageIndex];

        // Update the reasoning state
        baseHandleToggleReasoning(messageIndex);

        // Start the animation in next frame to ensure state is updated
        requestAnimationFrame(() => {
            startCollapseAnimation(messageIndex, isCurrentlyCollapsed);
        });
    }, [collapsedReasoning, baseHandleToggleReasoning, startCollapseAnimation]);

    // Stick-to-bottom instead of unconditional snap: during streaming,
    // `messages` changes every chunk and the old scrollTop assignment yanked
    // the user back down whenever they tried to scroll up. The shared hook
    // only re-sticks while the user is already near the bottom — except on
    // the user's OWN send (a new user-message tail), which always pins.
    const prevMsgCountRef = useRef(0);
    const newUserSend =
        messages.length > prevMsgCountRef.current &&
        !!messages[messages.length - 1]?.isUser;
    prevMsgCountRef.current = messages.length;
    const { ref: stickRef, onScroll: onStickScroll, pin } = useStickToBottom<HTMLDivElement>([messages]);
    if (newUserSend) pin(); // render-phase ref write — applied by the hook's effect after paint


    const messageElements = useMemo(
        () =>
            messages.map((message, index) => {
                const widthAnimation = animatingWidths[index];

                return (
                    <div key={index} className={cn(
                        "group flex flex-col",
                        message.isUser ? "mb-4" : "mb-4"
                    )}>
                        <MessageBubble
                            isUser={message.isUser}
                            bubbleRef={(el) => messageRefs.current[index] = el}
                            style={{
                                maxWidth: '85%',
                                width: widthAnimation ? `${widthAnimation.to}px` : 'fit-content',
                                transition: widthAnimation ? 'width 300ms ease-out' : undefined
                            }}
                        >
                        {/* Agentic steps - only show for AI messages - ABOVE the final message */}
                        {!message.isUser && message.agenticSteps && message.agenticSteps.length > 0 && (
                            <div
                                data-reasoning-section
                                className={cn(
                                    message.text ? "mb-2" : "mb-0"
                                )}
                            >
                                {/* If message is complete and has text, show collapsible reasoning */}
                                {message.text && message.isComplete && message.agenticSteps.every(step => step.status === 'completed') ? (
                                    <div>
                                        <button
                                            data-reasoning-button
                                            onClick={() => handleToggleReasoning(index)}
                                            className="flex items-center gap-2 py-1 text-xs text-muted-foreground hover:text-foreground/80 transition-colors w-full"
                                        >
                                            {collapsedReasoning[index] ? (
                                                <ChevronRight className="w-3 h-3 transition-transform duration-150" />
                                            ) : (
                                                <ChevronDown className="w-3 h-3 transition-transform duration-150" />
                                            )}
                                            <span>Reasoning ({message.agenticSteps.length} steps)</span>
                                        </button>
                                        
                                        <div 
                                            data-reasoning-content
                                            className={cn(
                                                "overflow-hidden transition-all duration-300 ease-out",
                                                collapsedReasoning[index] 
                                                    ? "max-h-0 opacity-0" 
                                                    : "opacity-100"
                                            )}
                                            style={{
                                                maxHeight: collapsedReasoning[index] 
                                                    ? '0px' 
                                                    : calculateMaxHeight(message.agenticSteps, index),
                                                display: hiddenFromLayout[index] ? 'none' : 'block'
                                            }}
                                        >
                                            <div className="pt-1 pl-2 pr-4">
                                                {updateStepsWithExpansion(message.agenticSteps, index).map((step, stepIndex) => (
                                                    <AgenticStepView
                                                        key={step.id}
                                                        step={step}
                                                        onToggleExpand={handleToggleExpand}
                                                        messageIndex={index}
                                                        stepIndex={stepIndex}
                                                        isFirstAppearance={false}
                                                    />
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    /* Streaming phase — keep steps collapsed by default; live status is shown at the bottom */
                                    <StreamingReasoning stepCount={message.agenticSteps.length}>
                                        {updateStepsWithExpansion(message.agenticSteps, index).map((step, stepIndex, arr) => (
                                            <AgenticStepView
                                                key={step.id}
                                                step={step}
                                                onToggleExpand={handleToggleExpand}
                                                messageIndex={index}
                                                stepIndex={stepIndex}
                                                isFirstAppearance={true}
                                                keepAnimating={!message.text && stepIndex === arr.length - 1 && !(message as any).wasInterrupted}
                                            />
                                        ))}
                                    </StreamingReasoning>
                                )}
                            </div>
                        )}

                        {/* User message */}
                        {message.isUser && message.n8nImportNodeCount !== undefined ? (
                            <N8nImportBadge
                                nodeCount={message.n8nImportNodeCount}
                                processing={n8nImport.nodeCount !== null}
                            />
                        ) : message.isUser && Array.isArray(message.content) && message.content.length > 0 ? (
                            /* Normal display mode for user messages with structured content */
                            <>
                                {message.content.map((item, contentIndex) => {
                                    if (item.type === 'text') {
                                        const textValue = item.text ?? '';
                                        if (textValue.trim().length === 0) {
                                            return null;
                                        }
                                        return (
                                            <MessageContentRenderer
                                                key={`text-${contentIndex}`}
                                                text={textValue}
                                            />
                                        );
                                    }
                                    if (item.type === 'image_url') {
                                        const imageValue = typeof item.image_url === 'string'
                                            ? item.image_url
                                            : item.image_url?.url;
                                        if (!imageValue) {
                                            return null;
                                        }

                                        // Check if this is a drawing image (marked with drawing: prefix)
                                        if (imageValue.startsWith('drawing:')) {
                                            // Parse the drawing data: "drawing:id:dataUrl"
                                            const parts = imageValue.split(':');
                                            const drawingId = parts[1];
                                            const drawingData = parts.slice(2).join(':'); // Rejoin in case data has colons

                                            // Render as a compact drawing tag with hover preview
                                            return (
                                                <div key={`drawing-${contentIndex}`} className="block">
                                                    <DrawingTagWithHover
                                                        drawingData={drawingData}
                                                    />
                                                </div>
                                            );
                                        }

                                        // Regular image handling
                                        return (
                                            <img
                                                key={`image-${contentIndex}`}
                                                src={imageValue}
                                                alt="User provided"
                                                className="block w-full max-w-full h-auto max-h-[500px] object-contain rounded-lg border border-border dark:border-white/20"
                                            />
                                        );
                                    }
                                    return null;
                                })}
                            </>
                        ) : !message.isUser && Array.isArray(message.content) && message.content.length > 0 ? (
                            // Assistant message with structured content
                            <>
                                {message.content.map((item, contentIndex) => {
                                    if (item.type === 'text') {
                                        const textValue = item.text ?? '';
                                        if (textValue.trim().length === 0) {
                                            return null;
                                        }
                                        return (
                                            <MarkdownRenderer
                                                key={`text-${contentIndex}`}
                                                content={textValue}
                                                className={cn(
                                                    "break-words overflow-wrap-anywhere",
                                                    message.agenticSteps?.length ? "text-foreground" : ""
                                                )}
                                            />
                                        );
                                    }
                                    if (item.type === 'image_url') {
                                        const imageValue = typeof item.image_url === 'string'
                                            ? item.image_url
                                            : item.image_url?.url;
                                        if (!imageValue) {
                                            return null;
                                        }

                                        // Regular image handling for assistant messages
                                        return (
                                            <img
                                                key={`image-${contentIndex}`}
                                                src={imageValue}
                                                alt="Assistant generated"
                                                className="block w-full max-w-full h-auto max-h-[500px] object-contain rounded-lg border border-border dark:border-white/20"
                                            />
                                        );
                                    }
                                    return null;
                                })}
                            </>
                        ) : message.text && (
                            message.isUser ? (
                                <MessageContentRenderer text={message.text} />
                            ) : (
                                <MarkdownRenderer
                                    content={message.text}
                                    className={cn(
                                        "break-words overflow-wrap-anywhere",
                                        message.agenticSteps?.length ? "text-foreground" : ""
                                    )}
                                />
                            )
                        )}

                        {/* Expandable tool steps log (live during edit, collapsed after) */}
                        {!message.isUser && message.editSteps && message.editSteps.length > 0 && (
                            <EditStepsView steps={message.editSteps} isComplete={message.isComplete || false} />
                        )}

                        {/* Inline edit segments — interleaved text and events for agentic edits */}
                        {/* Agentic edit prose. The node/edge events are consolidated
                            into BuilderProgress below (the Ledger footer), so here we
                            render only the text segments. */}
                        {!message.isUser && message.editSegments !== undefined && (() => {
                            const hasText = message.editSegments.some(seg => seg.type === 'text' && seg.text.trim().length > 0);
                            return hasText ? (
                                <div className="space-y-3">
                                    {message.editSegments.map((segment, segIndex) =>
                                        segment.type === 'text' && segment.text.trim().length > 0 ? (
                                            <MarkdownRenderer
                                                key={`seg-text-${segIndex}`}
                                                content={segment.text}
                                                className="break-words overflow-wrap-anywhere"
                                            />
                                        ) : null
                                    )}
                                </div>
                            ) : null;
                        })()}

                        {/* Workflow edit events — standalone display for non-agentic edits (legacy edit-stream compatibility) */}
                        {!message.isUser && message.workflowEditEvents && message.workflowEditEvents.length > 0 && !message.editSegments && (
                            <WorkflowEditEventView
                                events={message.workflowEditEvents}
                                isComplete={message.isComplete || message.workflowEditEvents.some(e => e.type === 'complete')}
                                workflowId={workflowId}
                            />
                        )}

                        {/* Builder progress — the Ledger footer: breathing-dot status
                            with pulse text, a clickable node list (switch to workflow
                            + pan), token count; collapses to a one-line summary once
                            the turn finishes. Handles plain replies (header only) and
                            renders nothing for a finished node-less reply. */}
                        {!message.isUser && !(message as any).wasInterrupted && (() => {
                            const lastAgentic = message.agenticSteps?.[message.agenticSteps.length - 1];
                            const lastEdit = message.editSteps?.[message.editSteps.length - 1];
                            const liveText =
                                message.editStatus ||
                                lastEdit ||
                                lastAgentic?.text ||
                                message.status ||
                                'Thinking';
                            const editEvents = message.editSegments
                                ? message.editSegments.flatMap(seg => (seg.type === 'events' ? seg.events : []))
                                : [];
                            // Only show the footer's separator when something rendered
                            // above it — otherwise a fresh bubble (nothing streamed yet)
                            // orphans a divider over empty space.
                            const hasContentAbove =
                                (message.agenticSteps?.length ?? 0) > 0 ||
                                (message.editSteps?.length ?? 0) > 0 ||
                                (Array.isArray(message.content) && message.content.length > 0) ||
                                (!!message.text && message.text.trim().length > 0) ||
                                (message.editSegments?.some(s => s.type === 'text' && s.text.trim().length > 0) ?? false);
                            return (
                                <BuilderProgress
                                    events={editEvents}
                                    status={liveText}
                                    genId={message.generationId}
                                    isComplete={!!message.isComplete}
                                    workflowId={workflowId}
                                    separated={hasContentAbove}
                                    failed={!!message.failed}
                                    error={message.error}
                                    errorCode={message.errorCode}
                                    errorMeta={message.errorMeta}
                                />
                            );
                        })()}

                        {/* Show interrupt message if the response was interrupted */}
                        {!message.isUser && (message as any).wasInterrupted && (
                            <div className="text-red-600 dark:text-red-400 text-xs mt-2 pt-2 border-border dark:border-white/10">
                                Response interrupted by user
                            </div>
                        )}

                        </MessageBubble>
                    </div>
                );
            }),
        [messages, collapsedReasoning, hiddenFromLayout, animatingWidths, handleToggleExpand, handleToggleReasoning, calculateMaxHeight, updateStepsWithExpansion, messageRefs, n8nImport.nodeCount]
    );

    return (
        <TooltipProvider>
            <div className="h-full relative">
                <div
                    className="absolute inset-0 right-1 overflow-y-auto scrollbar-subtle p-4"
                    ref={stickRef}
                    onScroll={onStickScroll}
                >
                    <div className="flex flex-col">
                        {messageElements}
                        <div ref={messagesEndRef} />
                    </div>
                </div>
            </div>
        </TooltipProvider>
    );
}

// Export memoized component to prevent re-renders when props don't change
export const MessagesView = memo(MessagesViewComponent);
