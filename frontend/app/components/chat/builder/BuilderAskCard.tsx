// The builder's question, docked on the composer: the step it's about, by its mark and the name the canvas shows (or
// its app), over the builder's own form, which asks it. Typing in the box under it answers in words instead.
import type { ReactNode } from 'react';
import { COMPOSER_SURFACE } from '~/components/chat/AgentChatComposer';
import { NodeMark } from '~/components/dashboard/primitives';
import { AutomationMark } from '~/components/shell/glyphs';
import { graphRecords } from '~/lib/liveGraphStore';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { cn } from '~/lib/utils';

/** What a question is about: the one step its answers are for, by its name on the canvas (a label that's only the
 *  builder's handle for it isn't one), else its app; or, when it asks about several, how many (drawn with the
 *  automation's mark). Never the question itself: the form under it asks that. */
export function askSubject(inputs: { nodeId: string; label: string; nodeType?: string }[], workflowId: string | null): { about: string; nodeType?: string } {
    const steps = [...new Set(inputs.map((input) => input.nodeId).filter(Boolean))];
    if (steps.length > 1) return { about: `${steps.length} steps need an answer` };
    const nodeType = inputs[0]?.nodeType;
    const node = steps[0] && workflowId ? graphRecords[workflowId]?.nodes.find((n) => n.id === steps[0]) : undefined;
    const label = node?.data?.label;
    const named = typeof label === 'string' && label !== node?.id ? label : undefined;
    return { about: named || (nodeType && getNodeIconMeta(nodeType)?.label) || 'The builder has a question', nodeType };
}

export function BuilderAskCard({ about, nodeType, children }: { about: string; nodeType?: string; children: ReactNode }) {
    return (
        <section className={cn('max-h-[min(56vh,540px)] overflow-y-auto rounded-[22px] px-4 pb-4 pt-3.5 scrollbar-subtle', COMPOSER_SURFACE)} data-testid="builder-ask">
            <header className="mb-3 flex items-center gap-3">
                {nodeType ? <NodeMark type={nodeType} size="md" /> : <AutomationMark className="h-6 w-6 shrink-0" />}
                <h3 className="min-w-0 flex-1 truncate text-[14.5px] font-medium leading-snug text-foreground">{about}</h3>
            </header>
            {children}
        </section>
    );
}
