/**
 * PublicWorkflowView - Read-only view for publicly shared workflows.
 * Displays the workflow canvas without editing capabilities.
 * Unauthenticated users can view; authenticated users can fork to their account.
 */

import { useState, useCallback, useEffect, useRef, useMemo, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router';
import { GitFork, LayoutGrid, Grid } from 'lucide-react';
import { Button } from '~/components/ui/button';
import { AuthModal } from '~/components/auth/AuthModal';
// Lazy-loaded so the workflow node registry (92 eager node-component imports) is NOT pulled
// into the embed iframe's main bundle. Defers ~hundreds of KB + heap until the user toggles
// to the canvas tab, which keeps the interface view light enough to render reliably on mobile.
const ReadOnlyFlowCanvas = lazy(() =>
    import('./ReadOnlyFlowCanvas').then(m => ({ default: m.ReadOnlyFlowCanvas }))
);
import { WorkflowProvider } from './WorkflowContext';
import { deriveInterfaceBlocks } from '~/utils/interfaceBlocks';
import { ReactFlowProvider } from '@xyflow/react';
import type { Node, Edge } from '@xyflow/react';

const WorkflowInterface = lazy(() =>
    import('~/components/interface/WorkflowInterface').then(m => ({ default: m.WorkflowInterface }))
);
import type { InterfaceGridState } from '~/components/interface/WorkflowInterface';

interface WorkflowData {
    nodes: Node[];
    edges: Edge[];
    interface?: InterfaceGridState | null;
}

interface DisplayMetadata {
    selectedNodeId?: string;
}

interface PublicWorkflow {
    id: string;
    name: string;
    description: string;
    workflow_data: WorkflowData;
    display_metadata: DisplayMetadata | null;
    owner_name: string;
}

interface PublicWorkflowViewProps {
    workflow: PublicWorkflow;
    isAuthenticated: boolean;
    isEmbed?: boolean;
    autoFork?: boolean;
    csrfToken?: string;
    /** Override the initial view ('canvas' or 'interface'). Defaults to 'interface' if blocks exist. */
    initialView?: 'canvas' | 'interface';
}

// Storage key for pending fork intent (survives page redirects after auth)
const PENDING_FORK_KEY = 'noclick_pending_fork_workflow';
// Storage key for fork workflow data (consumed by WorkflowBrowser on next mount)
const FORK_WORKFLOW_DATA_KEY = 'noclick_fork_workflow_data';

export function PublicWorkflowView({
    workflow,
    isAuthenticated,
    isEmbed = false,
    autoFork = false,
    csrfToken,
    initialView,
}: PublicWorkflowViewProps) {
    const navigate = useNavigate();
    const [showAuthModal, setShowAuthModal] = useState(false);
    const [pendingFork, setPendingFork] = useState(false);
    const hasForkTriggered = useRef(false);

    // Derive interface blocks from workflow nodes, excluding setup subgraph
    const workflowNodes = workflow.workflow_data?.nodes || [];
    const workflowEdges = workflow.workflow_data?.edges || [];
    const interfaceBlocks = useMemo(() =>
        deriveInterfaceBlocks(workflowNodes, workflowEdges),
    [workflowNodes, workflowEdges]);

    const hasInterface = interfaceBlocks.length > 0;
    const [activeView, setActiveView] = useState<'canvas' | 'interface'>(() => {
        if (initialView) return initialView === 'interface' && hasInterface ? 'interface' : 'canvas';
        return hasInterface ? 'interface' : 'canvas';
    });

    // Listen for view-switch messages from a parent iframe
    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            if (event.data?.type === 'noclick:setView' && (event.data.view === 'canvas' || event.data.view === 'interface')) {
                setActiveView(event.data.view);
            }
        };
        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    // Fork prompt shown when user tries to interact with read-only interface
    const [showForkPrompt, setShowForkPrompt] = useState(false);
    const forkPromptTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(
        undefined
    );
    const handleReadOnlyInteraction = useCallback(() => {
        setShowForkPrompt(true);
        clearTimeout(forkPromptTimeout.current);
        forkPromptTimeout.current = setTimeout(() => setShowForkPrompt(false), 4000);
    }, []);

    // Navigate to creator with workflow data for preview/editing before creating
    const performFork = useCallback(() => {
        // Store workflow data for the creator to load
        const forkData = {
            name: workflow.name,
            description: workflow.description || '',
            workflowData: {
                nodes: workflowNodes,
                edges: workflowEdges,
            },
            sourceId: workflow.id,
        };
        sessionStorage.setItem(FORK_WORKFLOW_DATA_KEY, JSON.stringify(forkData));

        // Navigate to dashboard with fork action - creator will load the data
        navigate('/dashboard?tab=workflows&action=fork');
    }, [workflow, navigate]);

    // Handle fork button click
    const handleFork = useCallback(() => {
        if (!isAuthenticated) {
            // Store fork intent and show auth modal
            if (typeof window !== 'undefined') {
                sessionStorage.setItem(PENDING_FORK_KEY, workflow.id);
            }
            setShowAuthModal(true);
            return;
        }

        performFork();
    }, [isAuthenticated, performFork, workflow.id]);

    // Check for pending fork on mount (after auth redirect or autoFork param)
    useEffect(() => {
        if (typeof window === 'undefined') return;
        if (hasForkTriggered.current) return;

        const pendingWorkflowId = sessionStorage.getItem(PENDING_FORK_KEY);
        if (isAuthenticated && pendingWorkflowId === workflow.id) {
            // User just logged in and had a pending fork - set flag
            sessionStorage.removeItem(PENDING_FORK_KEY);
            setPendingFork(true);
        } else if (isAuthenticated && autoFork) {
            // Auto-fork requested by the embedding page
            setPendingFork(true);
        } else if (!isAuthenticated && autoFork) {
            // Not authenticated but autoFork requested - show auth modal
            sessionStorage.setItem(PENDING_FORK_KEY, workflow.id);
            setShowAuthModal(true);
        }
    }, [isAuthenticated, workflow.id, autoFork]);

    // Execute pending fork when authenticated
    useEffect(() => {
        if (!pendingFork || hasForkTriggered.current) return;

        hasForkTriggered.current = true;
        setPendingFork(false);
        performFork();
    }, [pendingFork, performFork]);

    return (
        <div className="h-screen flex flex-col bg-background">
            {/* Header - hidden in embed mode.
                Mobile layout:
                  - title truncates instead of wrapping (flex-1 min-w-0)
                  - View toggle is icon-only under sm (label hidden)
                  - Fork CTA collapses to icon-only ("Fork") under sm
                  - All non-truncating items are shrink-0 so they keep their size */}
            {!isEmbed && (
                <header className="flex items-center justify-between gap-2 px-3 sm:px-4 h-14 border-b border-border bg-background/95 backdrop-blur-sm z-10">
                    <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                        {/* Workflow info — truncates on overflow instead of wrapping */}
                        <h1 className="text-base sm:text-lg font-semibold text-foreground leading-tight truncate min-w-0">
                            {workflow.name}
                        </h1>

                        {/* View toggle — styled as a segmented control so the
                            mobile icon-only variant still reads as a "two states,
                            pick one" toggle instead of two loose icons. Outer
                            wrapper carries the bg + border; buttons swap fill on
                            active. Labels stay hidden under sm to keep the header
                            on a single line on 375px viewports. */}
                        {hasInterface && (
                            <div className="flex shrink-0 items-center gap-0.5 ml-2 sm:ml-6 rounded-lg border border-border/80 dark:border-zinc-800/80 bg-sunken p-0.5">
                                <button
                                    onClick={() => setActiveView('interface')}
                                    aria-label="Interface"
                                    aria-pressed={activeView === 'interface'}
                                    className={`px-2.5 sm:px-3.5 py-1.5 text-sm font-semibold rounded-md flex items-center gap-2 transition-colors ${
                                        activeView === 'interface'
                                            ? 'text-foreground bg-secondary ring-1 ring-border/60 dark:ring-zinc-700/60'
                                            : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-card'
                                    }`}
                                >
                                    <LayoutGrid className="h-[18px] w-[18px] sm:h-4 sm:w-4" />
                                    <span className="hidden sm:inline">Interface</span>
                                </button>
                                <button
                                    onClick={() => setActiveView('canvas')}
                                    aria-label="Workflow"
                                    aria-pressed={activeView === 'canvas'}
                                    className={`px-2.5 sm:px-3.5 py-1.5 text-sm font-semibold rounded-md flex items-center gap-2 transition-colors ${
                                        activeView === 'canvas'
                                            ? 'text-foreground bg-secondary ring-1 ring-border/60 dark:ring-zinc-700/60'
                                            : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-card'
                                    }`}
                                >
                                    <Grid className="h-[18px] w-[18px] sm:h-4 sm:w-4" />
                                    <span className="hidden sm:inline">Workflow</span>
                                </button>
                            </div>
                        )}
                    </div>

                    <div className="flex shrink-0 items-center gap-3">
                        {/* Fork button — full label on sm+, short "Fork" on mobile */}
                        <Button
                            onClick={handleFork}
                            className="bg-primary text-primary-foreground hover:bg-primary/90"
                        >
                            <GitFork className="w-4 h-4 sm:mr-2" />
                            <span className="hidden sm:inline">Use This Template</span>
                            <span className="sm:hidden ml-1.5">Fork</span>
                        </Button>
                    </div>
                </header>
            )}

            {/* Description — hidden in embed mode and on mobile (eats vertical
                real estate that's better used by the canvas/interface itself) */}
            {!isEmbed && workflow.description && (
                <div className="hidden md:block px-4 py-2 border-b border-border bg-background/50">
                    <p className="text-sm text-muted-foreground">{workflow.description}</p>
                </div>
            )}

            {/* Content area — only the active view is mounted. Mounting both at once doubles
                 ReactFlow / grid-layout cost and reliably crashes mobile WebKit on workflow embeds. */}
            <div className="flex-1 relative bg-background min-h-0">
                {hasInterface && activeView === 'interface' && (
                    <div className="absolute inset-0 flex flex-col">
                        <WorkflowProvider workflowId={workflow.id} workflowName={workflow.name}>
                            <ReactFlowProvider>
                                <Suspense fallback={<div className="flex-1 bg-background" />}>
                                    <WorkflowInterface
                                        initialBlocks={interfaceBlocks}
                                        isReadOnly
                                        onReadOnlyInteraction={handleReadOnlyInteraction}
                                        savedState={workflow.workflow_data?.interface ?? null}
                                    />
                                </Suspense>
                            </ReactFlowProvider>
                        </WorkflowProvider>
                    </div>
                )}
                {activeView === 'canvas' && (
                    <div className="absolute inset-0">
                        <Suspense fallback={<div className="absolute inset-0 bg-background flex items-center justify-center text-muted-foreground dark:text-zinc-500 text-sm">Loading canvas…</div>}>
                            <ReadOnlyFlowCanvas
                                nodes={workflowNodes}
                                edges={workflowEdges}
                                onForkPrompt={handleReadOnlyInteraction}
                                isEmbed={isEmbed}
                            />
                        </Suspense>
                    </div>
                )}
            </div>

            {/* Fork prompt — appears when user tries to interact with read-only interface */}
            {showForkPrompt && (
                <>
                <style dangerouslySetInnerHTML={{ __html: `@keyframes fork-toast-in { from { opacity: 0; transform: translateX(-50%) translateY(16px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }` }} />
                <div
                    className="fixed bottom-6 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md"
                    style={{ animation: 'fork-toast-in 0.25s ease-out forwards' }}
                >
                    <div className="flex items-center gap-4 px-5 py-3 rounded-xl bg-card border border-border dark:border-zinc-700 shadow-2xl">
                        <span className="flex-1 min-w-0 text-sm text-foreground/80 leading-snug">Fork this workflow to edit it</span>
                        <button
                            onClick={() => {
                                setShowForkPrompt(false);
                                // When embedded in an iframe, navigate the top window to the share page with fork=true
                                if (isEmbed && window.top !== window.self) {
                                    window.top!.location.href = `/share/${workflow.id}?fork=true`;
                                } else {
                                    handleFork();
                                }
                            }}
                            className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors whitespace-nowrap"
                        >
                            <GitFork className="w-3.5 h-3.5" />
                            Fork
                        </button>
                    </div>
                </div>
                </>
            )}

            {/* Auth modal for unauthenticated fork attempts */}
            <AuthModal
                isOpen={showAuthModal}
                onClose={() => setShowAuthModal(false)}
                initialMode="signup"
                redirectTo={typeof window !== 'undefined' ? window.location.href : undefined}
                csrfToken={csrfToken}
            />
        </div>
    );
}
