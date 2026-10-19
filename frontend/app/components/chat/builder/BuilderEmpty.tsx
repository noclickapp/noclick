// A builder chat not started: the question in the pages' serif, a line saying what the builder changes (the
// automation open beside it, by its own mark), and a few starts drawn from what the automation has, each with the
// automation's own mark (its trigger, for when it runs) or a plain glyph, never another app's.
import type { ReactNode } from 'react';
import { useSnapshot } from 'valtio';
import { ArrowUpRight, Plus } from 'lucide-react';
import { NodeMark } from '~/components/dashboard/primitives';
import { AutomationMark } from '~/components/shell/glyphs';
import { DISPLAY } from '~/components/shell/titles';
import { graphRecords } from '~/lib/liveGraphStore';
import { cn } from '~/lib/utils';

interface Start {
    title: string;
    mark: ReactNode;
    prompt: string;
    /** Complete as it is, so it goes at once; otherwise it lands in the composer to finish. */
    send?: boolean;
}

/** What the automation has, read from its live graph: steps at all, and something that starts it. */
function useGraphShape(workflowId?: string): { steps: number; trigger: string | undefined } {
    const records = useSnapshot(graphRecords);
    const nodes = (workflowId ? records[workflowId]?.nodes : undefined) ?? [];
    const types = nodes.map((n) => n.type ?? '').filter((t) => t && !t.startsWith('sticky'));
    return { steps: types.length, trigger: types.find((t) => t.startsWith('trigger-')) };
}

export function BuilderEmpty({
    workflowId,
    workflowName,
    isMobile,
    onStart,
}: {
    workflowId?: string;
    workflowName?: string;
    isMobile: boolean;
    /** A start picked: send its prompt, or put it in the composer to finish. */
    onStart: (prompt: string, send: boolean) => void;
}) {
    const shape = useGraphShape(workflowId);
    const name = workflowName || 'this automation';
    const starts: Start[] = shape.steps
        ? [
              { title: 'Explain what it does', mark: <AutomationMark className="h-4 w-4" />, prompt: `Explain what ${name} does, step by step.`, send: true },
              ...(shape.trigger ? [{ title: 'Change when it runs', mark: <NodeMark type={shape.trigger} size="sm" />, prompt: `Change when ${name} runs to ` }] : []),
              { title: 'Add a step', mark: <Plus className="h-4 w-4 text-foreground/70" strokeWidth={1.75} />, prompt: `Add a step that ` },
          ]
        : [];
    return (
        <div className="flex min-h-full flex-col justify-center px-5 pb-8 pt-10" data-testid="builder-empty">
            <h2 className={cn(DISPLAY, 'text-[36px] leading-[1.04] text-foreground')}>{shape.steps ? 'What should change?' : 'What should it do?'}</h2>
            <p className="mt-3 text-[13.5px] leading-relaxed text-muted-foreground">
                The builder edits{' '}
                <span className="whitespace-nowrap text-foreground">
                    <AutomationMark className="-mt-0.5 mr-1 inline h-3.5 w-3.5" />
                    {workflowName || 'the automation'}
                </span>
                , the automation {isMobile ? 'you have open' : 'open beside it'}
                {shape.steps ? ': a step, when it runs, what its agent is told, or a fix.' : '. Describe it and it draws it on the canvas.'}
            </p>
            {starts.length > 0 && (
                <div className="mt-6 flex flex-col gap-2">
                    {starts.map((start) => (
                        <button
                            key={start.title}
                            type="button"
                            onClick={() => onStart(start.prompt, !!start.send)}
                            className="group flex h-12 items-center gap-3 rounded-2xl px-3 text-left ring-1 ring-inset ring-border/70 transition-colors hover:bg-foreground/[0.025] hover:ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.07] dark:hover:bg-foreground/[0.03] dark:hover:ring-foreground/[0.12]"
                        >
                            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-foreground/[0.05]">{start.mark}</span>
                            <span className="min-w-0 flex-1 truncate text-[14px] text-foreground/90">{start.title}</span>
                            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
