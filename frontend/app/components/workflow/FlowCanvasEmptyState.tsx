// Centered overlay shown on top of an empty FlowCanvas (nodes.length === 0).
// Offers new users two starting points — Workflow or Interface — plus a
// natural-language prompt that hands off to the agentic builder in the sidebar.
// Disappears automatically the moment the workflow gains its first node.

import { useEffect, useRef, useState, type JSX } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowRight, CornerDownLeft } from 'lucide-react';
import { cn } from '~/lib/utils';
import { BorderBeam } from '~/components/ui/BorderBeam';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { useIsStreamingForWorkflow } from '~/hooks/useConversation';
import { useEffectiveWorkflowId } from '~/components/workflow/WorkflowContext';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useRibbonPhrase } from '~/hooks/useRibbonPhrase';
import { RibbonText } from '~/components/ui/RibbonText';
import { useN8nImportStatus } from '~/hooks/useN8nImportStatus';
import { N8nImportBadge } from '~/components/workflow/N8nImportBadge';
import { SendButton } from '~/components/chat/SendButton';

const CANVAS_PROMPT_SUGGESTIONS = [
    'Reply to customer support emails using my docs',
    'Summarize my Slack channels every morning',
    'Scrape Hacker News and post top stories to Discord',
    'Generate weekly KPI reports from Postgres',
];

const CANVAS_PROMPT_SUGGESTIONS_MOBILE = [
    'Post HN stories to Discord',
    'Summarize Slack channels',
    'Reply to support emails',
    'Weekly KPI reports',
];

const INTERFACE_PROMPT_SUGGESTIONS = [
    'A form to collect customer feedback',
    'A chatbot UI for my product docs',
    'A dashboard showing my latest sales metrics',
    'A file upload page for my team to share assets',
];

const INTERFACE_PROMPT_SUGGESTIONS_MOBILE = [
    'Sales metrics dashboard',
    'Customer feedback form',
    'Product docs chatbot',
    'Team file upload',
];

/** Canvas background preview — the ReactFlow cross pattern */
function CanvasPreview({ className }: { className?: string }) {
    return (
        <div className={cn('relative overflow-hidden rounded-lg bg-background', className)}>
            <svg className="absolute inset-0 w-full h-full" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <pattern id="empty-state-cross-pattern" width="8" height="8" patternUnits="userSpaceOnUse">
                        <path d="M 4 0 L 4 8 M 0 4 L 8 4" style={{ stroke: 'hsl(var(--border))' }} strokeWidth="0.5" fill="none" />
                    </pattern>
                </defs>
                <rect width="100%" height="100%" fill="url(#empty-state-cross-pattern)" />
            </svg>
        </div>
    );
}

/** Interface preview — a tiny dashboard mockup of UI blocks */
function InterfacePreview({ className }: { className?: string }) {
    return (
        <div className={cn('relative overflow-hidden rounded-lg bg-background p-1.5 flex flex-col gap-1', className)}>
            <div className="flex gap-1 flex-1">
                <div className="flex-1 rounded-sm bg-foreground/[0.08] border border-foreground/[0.06]" />
                <div className="w-1/3 rounded-sm bg-foreground/[0.05] border border-foreground/[0.06]" />
            </div>
            <div className="h-1/3 rounded-sm bg-foreground/[0.05] border border-foreground/[0.06]" />
        </div>
    );
}

interface FlowCanvasEmptyStateProps {
    /** Current active tab — Workflow vs Interface indicator highlights the active one. */
    activeTab: 'canvas' | 'interface';
    /** Switch the canvas tab (used by the Interface button). */
    onSwitchTab: (tab: 'canvas' | 'interface') => void;
}

interface TabPickerButtonProps {
    label: string;
    active: boolean;
    onSelect: () => void;
    Preview: (props: { className?: string }) => JSX.Element;
    compact?: boolean;
    tooltip: string;
}

function TabPickerButton({ label, active, onSelect, Preview, compact, tooltip }: TabPickerButtonProps) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <button
                    onClick={onSelect}
                    className={cn(
                        'group flex flex-col items-center rounded-xl border transition-all duration-150 ease-out',
                        compact ? 'gap-1 p-2' : 'gap-1.5 p-2.5',
                        active
                            ? 'bg-accent dark:bg-zinc-800/80 border-muted-foreground/50 dark:border-zinc-600 ring-1 ring-foreground/10 shadow-lg dark:shadow-black/40'
                            : 'bg-sunken border-border/70 dark:border-zinc-800/70 hover:border-border dark:hover:border-zinc-700 hover:bg-muted dark:hover:bg-zinc-900',
                    )}
                >
                    <div className={cn("transition-transform duration-150 ease-out group-hover:scale-105", compact ? "w-12 h-12" : "w-16 h-16")}>
                        <Preview
                            className={cn(
                                'w-full h-full border transition-colors duration-150 ease-out',
                                active ? 'border-muted-foreground' : 'border-border dark:border-zinc-700 group-hover:border-muted-foreground/50 dark:group-hover:border-zinc-600',
                            )}
                        />
                    </div>
                    <span
                        className={cn(
                            'transition-colors duration-150 ease-out',
                            compact ? 'text-xs' : 'text-sm',
                            active ? 'text-foreground font-medium' : 'text-muted-foreground dark:text-white/60 group-hover:text-foreground',
                        )}
                    >
                        {label}
                    </span>
                </button>
            </TooltipTrigger>
            <TooltipContent
                side="bottom"
                sideOffset={10}
                className="rounded-lg border border-border dark:border-zinc-700/60 bg-popover/95 px-3 py-1.5 text-xs font-medium tracking-tight text-popover-foreground dark:text-zinc-200 shadow-2xl dark:shadow-black/60 backdrop-blur-md"
            >
                {tooltip}
            </TooltipContent>
        </Tooltip>
    );
}

export function FlowCanvasEmptyState({ activeTab, onSwitchTab }: FlowCanvasEmptyStateProps) {
    const isMobile = useIsMobile(768);
    const [prompt, setPrompt] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const promptInputRef = useRef<HTMLTextAreaElement>(null);

    const n8nImport = useN8nImportStatus();
    const suggestions = isMobile
        ? (activeTab === 'interface' ? INTERFACE_PROMPT_SUGGESTIONS_MOBILE : CANVAS_PROMPT_SUGGESTIONS_MOBILE)
        : (activeTab === 'interface' ? INTERFACE_PROMPT_SUGGESTIONS : CANVAS_PROMPT_SUGGESTIONS);
    const ribbonPaused = !!prompt || n8nImport.nodeCount !== null;
    const { phrase, tick } = useRibbonPhrase(suggestions, ribbonPaused);

    // Mirror the actual sidebar agent state — the spinner stops when the
    // builder finishes (complete/error/user-stopped) instead of looping
    // forever on local `submitting`. The local flag still bridges the
    // window between submit click and the agent's first 'started' event.
    const isAgentResponding = useIsStreamingForWorkflow(useEffectiveWorkflowId());
    const sawAgentRespondingRef = useRef(false);
    useEffect(() => {
        if (isAgentResponding) {
            sawAgentRespondingRef.current = true;
        } else if (sawAgentRespondingRef.current) {
            sawAgentRespondingRef.current = false;
            setSubmitting(false);
        }
    }, [isAgentResponding]);
    const showSpinner = submitting || isAgentResponding;

    useEffect(() => {
        promptInputRef.current?.focus();
    }, []);

    // Hero hand-off: WorkflowBrowser stashes `{prompt, tab}` under
    // `noclick:hero-prompt:pending` before creating the blank workflow that
    // mounts this overlay. Consume once, switch the tab, populate the textarea
    // for visibility, and dispatch the same builder events handleSubmit fires.
    const heroPromptConsumedRef = useRef(false);
    useEffect(() => {
        if (heroPromptConsumedRef.current || typeof window === 'undefined') return;
        const raw = sessionStorage.getItem('noclick:hero-prompt:pending');
        if (!raw) return;
        heroPromptConsumedRef.current = true;
        sessionStorage.removeItem('noclick:hero-prompt:pending');
        let parsed: { prompt?: string; tab?: 'canvas' | 'interface' } | null = null;
        try {
            parsed = JSON.parse(raw);
        } catch {
            return;
        }
        const trimmed = parsed?.prompt?.trim();
        if (!trimmed) return;
        if (parsed?.tab && parsed.tab !== activeTab) {
            onSwitchTab(parsed.tab);
        }
        setPrompt(trimmed);
        setSubmitting(true);
        document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
        document.dispatchEvent(new CustomEvent('noclick:builder:submit', { detail: { prompt: trimmed } }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleSubmit = () => {
        const trimmed = prompt.trim();
        if (!trimmed || submitting) return;
        setSubmitting(true);
        // Expand the chat sidebar and hand the prompt to the agentic builder.
        // Usage state updates from the backend once the LLM call settles.
        document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
        document.dispatchEvent(new CustomEvent('noclick:builder:submit', { detail: { prompt: trimmed } }));
    };

    // Stop button on the empty-state SendButton routes through the same
    // sidebar handler ChatBox uses, so the backend builder actually halts
    // (sends agent:pause + clears in-flight state) instead of just turning
    // the spinner off locally.
    const handleStop = () => {
        document.dispatchEvent(new CustomEvent('noclick:builder:stop'));
        setSubmitting(false);
    };

    return (
        <motion.div
            className={cn("absolute inset-0 z-30 flex justify-center pointer-events-none", isMobile ? "items-start pt-20" : "items-center pb-16")}
            aria-label="Empty workflow starting guide"
            initial={{ opacity: 0, filter: 'blur(10px)' }}
            animate={{ opacity: 1, filter: 'blur(0px)' }}
            exit={{ opacity: 0, filter: 'blur(10px)' }}
            transition={{ duration: 0.28, ease: 'easeOut' }}
        >
            <div className="pointer-events-auto flex flex-col items-center w-full max-w-3xl px-6">
                {/* Title */}
                <div className={cn("text-center", isMobile ? "mb-4" : "mb-5")}>
                    <h1 className={cn("font-medium text-foreground tracking-tight", isMobile ? "text-3xl" : "text-5xl")}>
                        Build something
                    </h1>
                </div>

                {/* Interface / Workflow picker — order matches the top navbar tabs */}
                <TooltipProvider delayDuration={200}>
                    <div className={cn("flex justify-center gap-3", isMobile ? "mb-4" : "mb-5")}>
                        <TabPickerButton
                            label="Interface"
                            active={activeTab === 'interface'}
                            onSelect={() => onSwitchTab('interface')}
                            Preview={InterfacePreview}
                            compact={isMobile}
                            tooltip="Build a custom UI — forms, dashboards."
                        />
                        <TabPickerButton
                            label="Workflow"
                            active={activeTab === 'canvas'}
                            onSelect={() => onSwitchTab('canvas')}
                            Preview={CanvasPreview}
                            compact={isMobile}
                            tooltip="Automate a task — emails, reports, alerts."
                        />
                    </div>
                </TooltipProvider>

                {/* Prompt input — multi-line textarea with rotating ribbon placeholder.
                    Enter submits, Shift+Enter inserts a newline. */}
                <div className="w-full flex justify-center">
                    <div className="relative flex-1 min-w-0 max-w-3xl">
                        <div
                            onClick={() => promptInputRef.current?.focus()}
                            className="group/input relative rounded-2xl w-full overflow-hidden cursor-text bg-sunken border border-input dark:border-zinc-800/70 focus-within:border-muted-foreground/50 dark:focus-within:border-zinc-600 shadow-xl dark:shadow-black/40 transition-colors"
                        >
                            {/* n8n import indicator — sits at the top of the textarea so the
                                user can see their pasted workflow is being translated. */}
                            {n8nImport.nodeCount !== null && (
                                <div className={cn('relative z-10', isMobile ? 'pt-3 px-4' : 'pt-4 px-7')}>
                                    <N8nImportBadge nodeCount={n8nImport.nodeCount} processing />
                                </div>
                            )}
                            <textarea
                                ref={promptInputRef}
                                value={prompt}
                                onChange={(e) => setPrompt(e.target.value)}
                                onKeyDown={(e) => {
                                    // Enter submits; Shift+Enter inserts a newline.
                                    if (e.key === 'Enter' && !e.shiftKey && prompt.trim() && !showSpinner) {
                                        e.preventDefault();
                                        handleSubmit();
                                        return;
                                    }
                                    // Tab / Right-arrow autocompletes the rotating ribbon hint when
                                    // the textarea is empty — same affordance Copilot-style ghosts use.
                                    if (!prompt && n8nImport.nodeCount === null && (e.key === 'Tab' || e.key === 'ArrowRight')) {
                                        e.preventDefault();
                                        setPrompt(phrase);
                                    }
                                }}
                                placeholder=""
                                disabled={showSpinner || n8nImport.nodeCount !== null}
                                rows={3}
                                className={cn(
                                    'block w-full resize-none bg-transparent text-foreground outline-none leading-relaxed relative z-10',
                                    isMobile ? 'text-base px-4 py-4 pr-14' : 'text-xl px-7 py-5 pr-16',
                                )}
                            />
                            {!prompt && n8nImport.nodeCount === null && (
                                <div
                                    key={tick}
                                    className={cn(
                                        // ph-no-capture: decorative churn — remounts every 2.9s;
                                        // keep it out of the rrweb session-replay stream.
                                        'ph-no-capture pointer-events-none absolute z-0 text-muted-foreground dark:text-zinc-500 leading-relaxed',
                                        isMobile ? 'top-4 left-4 right-14 text-base' : 'top-5 left-7 right-16 text-xl',
                                    )}
                                >
                                    {/* Affordance: press Tab or → to fill the textarea with the hint.
                                        Rendered as two physical-looking keycaps (subtle gradient + inset
                                        highlight + drop shadow). Faded in after the phrase finishes
                                        typing so the keys never land before the text they refer to. */}
                                    <RibbonText
                                        phrase={phrase}
                                        trailing={
                                            <>
                                                <kbd className="inline-flex items-center justify-center h-[22px] px-1.5 rounded-[5px] border border-foreground/10 bg-foreground/[0.06] text-[10px] leading-none font-sans font-medium text-muted-foreground shadow-sm dark:border-border/80 dark:bg-gradient-to-b dark:from-zinc-800 dark:to-zinc-900 dark:text-foreground/80 dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06),0_1px_0_0_rgba(0,0,0,0.6),0_2px_3px_-1px_rgba(0,0,0,0.5)]">
                                                    Tab
                                                </kbd>
                                                <kbd className="inline-flex items-center justify-center w-[22px] h-[22px] rounded-[5px] border border-foreground/10 bg-foreground/[0.06] text-muted-foreground shadow-sm dark:border-border/80 dark:bg-gradient-to-b dark:from-zinc-800 dark:to-zinc-900 dark:text-foreground/80 dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06),0_1px_0_0_rgba(0,0,0,0.6),0_2px_3px_-1px_rgba(0,0,0,0.5)]">
                                                    <ArrowRight className="w-3 h-3" strokeWidth={2.5} />
                                                </kbd>
                                            </>
                                        }
                                    />
                                </div>
                            )}
                            <div
                                className={cn('absolute z-20', isMobile ? 'bottom-3 right-3' : 'bottom-4 right-4')}
                                onClick={(e) => e.stopPropagation()}
                            >
                                <SendButton
                                    onClick={handleSubmit}
                                    onInterrupt={handleStop}
                                    hasContent={!!prompt.trim()}
                                    isWaitingForResponse={showSpinner}
                                    showBorder={!!prompt.trim()}
                                    size="lg"
                                />
                            </div>
                        </div>
                        {/* Beam lives OUTSIDE the container's overflow-hidden clip so its ring
                            sits ON the 1px border, not 1px inside it — which left a white
                            sliver in light. inset-0 on this relative parent == the container's
                            border box (it's w-full here). */}
                        {!prompt && (
                            <BorderBeam
                                className="rounded-2xl"
                                duration={10}
                                borderWidth={1.5}
                                size={480}
                                colorFrom="transparent"
                                colorTo="hsl(var(--foreground) / 0.5)"
                            />
                        )}
                    </div>
                </div>

                {/* Suggestion pills — tab-aware, with the CornerDownRight enter icon to
                    hint that selecting one drops it into the prompt box.
                    Fixed-height container + absolute-positioned inner motion.div so
                    the pills never affect the surrounding block's height — switching
                    tabs would otherwise change the wrap-count and shift the textbox
                    up/down through the items-center re-center. */}
                <div className={cn(
                    "relative w-full mt-5",
                    isMobile ? "h-[170px]" : "h-[120px]",
                )}>
                    <AnimatePresence mode="wait" initial={false}>
                        <motion.div
                            key={activeTab}
                            className={cn(
                                "absolute inset-x-0 top-0 flex justify-center gap-2",
                                isMobile ? "flex-col items-center" : "flex-wrap content-start",
                            )}
                            initial={{ opacity: 0, filter: 'blur(6px)' }}
                            animate={{ opacity: 1, filter: 'blur(0px)' }}
                            exit={{ opacity: 0, filter: 'blur(6px)' }}
                            transition={{ duration: 0.2, ease: 'easeOut' }}
                        >
                            {suggestions.map((suggestion) => (
                                <button
                                    key={suggestion}
                                    onClick={() => {
                                        setPrompt(suggestion);
                                        promptInputRef.current?.focus();
                                    }}
                                    disabled={showSpinner}
                                    className={cn(
                                        'group/chip flex items-center gap-1.5 pl-3 pr-2.5 py-1.5 rounded-full text-sm text-muted-foreground dark:text-white/55 bg-sunken border border-border/70 dark:border-zinc-800/70 dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)] hover:bg-muted dark:hover:bg-zinc-900 hover:border-border dark:hover:border-zinc-700 hover:text-foreground/90 transition-all duration-200 ease-out',
                                        showSpinner && 'opacity-50 cursor-not-allowed',
                                    )}
                                >
                                    {suggestion}
                                    <CornerDownLeft
                                        className="w-3.5 h-3.5 text-foreground/25 group-hover/chip:text-foreground/60 transition-colors duration-200"
                                        strokeWidth={1.75}
                                    />
                                </button>
                            ))}
                        </motion.div>
                    </AnimatePresence>
                </div>

            </div>

        </motion.div>
    );
}
