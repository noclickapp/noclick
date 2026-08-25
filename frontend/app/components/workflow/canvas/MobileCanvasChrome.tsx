import { AlertCircle, FolderOpen, Play, X } from 'lucide-react';
import { useSnapshot } from 'valtio';
import { activeGenStore } from '~/lib/activeGenStore';
import { ThinkingOrb, orbStateForStatus } from '~/components/shared/ThinkingOrb';

// Mobile-only presentational chrome for FlowCanvas:
// - <MobileRunPill>            top-right run/stop toggle
// - <MobileResourcesPill>      top-left resources shortcut (when any resources exist)
// - <MobileBuilderStatusPill>  bottom-center live AI-builder status → tap to open chat
// - <MobileErrorBanner>        bottom error-notification queue with auto-dismiss bar
//
// Kept as dumb presentational components so the bulk of FlowCanvas.tsx
// doesn't get tangled up in mobile-specific JSX branches.

interface MobileRunPillProps {
    isWorkflowRunning: boolean;
    activeExecutionCount: number;
    onRun: () => void;
    onStop: () => void;
}

export function MobileRunPill({ isWorkflowRunning, activeExecutionCount, onRun, onStop }: MobileRunPillProps) {
    return (
        <div className="absolute top-12 right-4 pt-2 z-10 pointer-events-none">
            <button
                onClick={isWorkflowRunning ? onStop : onRun}
                className={`pointer-events-auto relative overflow-hidden h-9 px-6 rounded-full text-sm font-semibold flex items-center gap-1.5 shadow-lg ${
                    isWorkflowRunning
                        ? 'bg-secondary text-secondary-foreground border border-border dark:border-zinc-700'
                        : 'bg-primary text-primary-foreground'
                }`}
                aria-label={isWorkflowRunning ? 'Stop workflow' : 'Run workflow'}
            >
                {isWorkflowRunning && (
                    <div
                        className="absolute inset-0 rounded-full"
                        style={{
                            background: 'linear-gradient(90deg, hsl(var(--secondary)) 0%, hsl(var(--accent)) 35%, hsl(var(--muted-foreground) / 0.45) 50%, hsl(var(--accent)) 65%, hsl(var(--secondary)) 100%)',
                            backgroundSize: '300% 100%',
                            animation: 'gradient-move 2s linear infinite',
                        }}
                    />
                )}
                <span className="relative flex items-center gap-1.5">
                    {isWorkflowRunning ? <X className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                    {isWorkflowRunning
                        ? activeExecutionCount > 1 ? `Stop (${activeExecutionCount})` : 'Stop'
                        : 'Run'}
                </span>
            </button>
        </div>
    );
}

interface MobileResourcesPillProps {
    onClick: () => void;
}

export function MobileResourcesPill({ onClick }: MobileResourcesPillProps) {
    return (
        <div className="absolute top-12 left-4 pt-2 z-10">
            <button
                onClick={onClick}
                className="h-9 px-4 rounded-full text-sm font-semibold flex items-center gap-1.5 shadow-lg bg-secondary text-secondary-foreground border border-border dark:border-zinc-700"
            >
                <FolderOpen className="h-3.5 w-3.5 opacity-80" />
                Resources
            </button>
        </div>
    );
}

interface MobileBuilderStatusPillProps {
    workflowId: string;
    onOpenChat: () => void;
}

// Surfaces the live AI-builder status (e.g. "Adding Slack node") while it edits
// the open workflow. Tapping jumps to the chat view so the user can read the
// full stream / answer any prompts. Bottom-center so it clears the top run/
// resources pills and the bottom-left incomplete-node navigator.
//
// Subscribes to activeGenStore itself (rather than reading status from a prop)
// so status frames re-render only this pill — not the heavy FlowCanvas — which
// matters for mobile performance. Renders nothing when no run is active.
export function MobileBuilderStatusPill({ workflowId, onOpenChat }: MobileBuilderStatusPillProps) {
    const snap = useSnapshot(activeGenStore);
    const ids = snap.byWorkflow[workflowId];
    let status: string | null = null;
    if (ids) {
        for (let i = ids.length - 1; i >= 0; i--) {
            const gen = snap.gens[ids[i]];
            if (gen && !gen.stopped) { status = gen.status || 'Thinking…'; break; }
        }
    }
    if (!status) return null;

    return (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 pointer-events-none max-w-[85%]">
            <button
                onClick={onOpenChat}
                className="pointer-events-auto h-9 pl-3 pr-4 rounded-full text-sm font-medium flex items-center gap-2 shadow-lg bg-secondary/90 backdrop-blur-sm text-secondary-foreground border border-border dark:border-zinc-700"
                aria-label="Open chat"
            >
                <ThinkingOrb state={orbStateForStatus(status)} className="shrink-0" aria-label={status} />
                <span className="truncate">{status}</span>
            </button>
        </div>
    );
}

interface MobileErrorItem {
    id: string;
    title: string;
    description: string;
}

interface MobileErrorBannerProps {
    errors: MobileErrorItem[];
}

// Renders the front-of-queue error with an auto-dismiss progress bar.
// The caller owns the error queue + its dequeue timer.
export function MobileErrorBanner({ errors }: MobileErrorBannerProps) {
    if (errors.length === 0) return null;
    const front = errors[0];

    return (
        <div className="absolute bottom-0 inset-x-0 z-50 px-4 pb-4 pointer-events-none">
            <div
                key={front.id}
                className="rounded-xl overflow-hidden pointer-events-auto backdrop-blur-md border bg-red-100/90 border-red-300/80 dark:bg-red-900/75 dark:border-red-600/35"
            >
                <div className="px-4 py-3 flex items-start gap-3">
                    <AlertCircle className="w-4 h-4 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-red-900 dark:text-red-200">{front.title}</p>
                        {front.description && (
                            <p className="text-xs text-red-800/80 dark:text-red-300/80 mt-0.5 line-clamp-2">{front.description}</p>
                        )}
                    </div>
                    {errors.length > 1 && (
                        <span className="text-xs text-red-700/60 dark:text-red-400/60 shrink-0 mt-0.5">+{errors.length - 1}</span>
                    )}
                </div>
                <div
                    key={`p-${front.id}`}
                    className="h-[3px] bg-red-500/70"
                    style={{ animation: 'toast-shrink 4s linear forwards' }}
                />
            </div>
        </div>
    );
}
