// A builder turn's work, as the panel draws it under a request. While it runs: one line of what it's doing now (the
// working orb and the op its current batch is on, each new one rising in as the last leaves; the run's status
// between batches) and under it the words of the turn it's on. Once it ends: "9 actions", folding open to each
// action in order with what the builder said on the way, an action that failed saying so and why, one its run never
// finished saying that. Then the steps of
// the canvas it touched, each with what's happening to it or what changed, opening that step on the canvas when picked.
import { useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, X } from 'lucide-react';
import { FreshCheck, Swap } from '~/components/coordinator/inline/motion';
import { NodeMark } from '~/components/dashboard/primitives';
import { ThinkingOrb, type OrbState } from '~/components/shared/ThinkingOrb';
import { stepWords, type BuilderStep, type WorkItem } from '~/lib/builderSteps';
import { fieldTitle, useFieldTitles } from '~/lib/fieldTitles';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { cn } from '~/lib/utils';
import { navigateToNode } from '~/utils/workflowNavigation';
import type { BuilderProgressNode } from '../builderProgress/model';

const LOOKS = new Set(['query_operations', 'query_schema', 'search_credentials', 'list_workflows', 'read', 'read_config', 'get_output', 'list_outputs', 'list_folders']);
const RUNS = new Set(['run_node', 'run_test', 'bash']);

/** The working orb for what an op does: looking something up, running something, or shaping the canvas. */
function orbFor(step: BuilderStep | undefined): OrbState {
    if (!step) return 'breathing';
    return LOOKS.has(step.op) ? 'searching' : RUNS.has(step.op) ? 'solving' : 'shaping';
}

function Said({ head, tail, muted }: { head: string; tail?: string; muted?: boolean }) {
    return (
        <span className="flex min-w-0 items-baseline overflow-hidden">
            <span className={cn('shrink-0', muted ? 'text-muted-foreground' : 'text-foreground/85')}>{head}</span>
            {tail && <span className="min-w-0 overflow-hidden text-ellipsis whitespace-pre text-muted-foreground/70">{tail}</span>}
        </span>
    );
}

/** What a running turn is on: the op of the batch running now, else the run's status; then the words of its turn. */
export function BuilderLive({ step, said, status }: { step?: BuilderStep; said?: string; status?: string }) {
    useFieldTitles([step?.node_type]);
    const line = step ? stepWords(step, 'doing') : { head: status || 'Thinking' };
    return (
        <div className="flex flex-col gap-1" data-testid="builder-live">
            <div className="flex h-6 items-center gap-2.5 text-[13.5px]" aria-live="polite" data-testid="builder-step-now">
                <ThinkingOrb state={orbFor(step)} size={20} style={{ width: 18, height: 18 }} aria-label={line.head} />
                <Swap id={step ? `step-${step.batch}-${step.index}` : `status-${line.head}`} className="min-w-0 flex-1">
                    <Said head={line.head} tail={line.tail} />
                </Swap>
            </div>
            {said && <p className="line-clamp-3 pl-7 text-[13px] leading-5 text-muted-foreground" data-testid="builder-said-now">{said}</p>}
        </div>
    );
}

/** In a turn that has ended, an action still running never finished: its run stopped under it. */
const unfinished = (step: BuilderStep) => step.state === 'running';
const wentWrong = (step: BuilderStep) => step.state === 'failed' || unfinished(step);

/** One action in the fold: what it did, or that it couldn't and why, or that it never finished. */
function Action({ step }: { step: BuilderStep }) {
    const failed = step.state === 'failed';
    const { head, tail } = stepWords(step, failed ? 'failed' : unfinished(step) ? 'doing' : 'done');
    const why = failed ? step.reason : unfinished(step) ? 'didn’t finish' : undefined;
    return (
        <li className="flex items-start gap-2" data-testid={failed ? 'builder-action-failed' : unfinished(step) ? 'builder-action-unfinished' : 'builder-action'}>
            <span className="mt-[3px] flex w-3.5 shrink-0 justify-center">
                {wentWrong(step) ? <X className="h-3.5 w-3.5 text-red-600/70 dark:text-red-400/70" strokeWidth={2.25} /> : <span className="mt-[5px] h-1 w-1 rounded-full bg-foreground/25" />}
            </span>
            <span className="min-w-0 flex-1">
                <Said head={head} tail={tail} muted />
                {why && <span className="block text-[12.5px] leading-[18px] text-muted-foreground/80">{why}</span>}
            </span>
        </li>
    );
}

/** A finished turn's actions, folded to how many there were; open, each in order with what was said on the way.
 *  `legacy`: a turn from before the builder reported its ops has only its status lines. */
export function BuilderActions({ items, legacy }: { items: WorkItem[]; legacy: string[] }) {
    useFieldTitles(items.map((item) => (item.kind === 'step' ? item.step.node_type : undefined)));
    const [open, setOpen] = useState(false);
    const count = items.filter((item) => item.kind === 'step').length || legacy.length;
    const failed = items.some((item) => item.kind === 'step' && wentWrong(item.step));
    if (!count) {
        // Nothing done, only words on the way: they read as they were said.
        return items.length ? (
            <div className="flex flex-col gap-1.5">
                {items.map((item, i) => item.kind === 'said' && <p key={i} className="text-[13.5px] leading-relaxed text-muted-foreground">{item.text}</p>)}
            </div>
        ) : null;
    }
    return (
        <div data-testid={failed ? 'builder-actions-failed' : 'builder-actions'}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                className="flex h-6 items-center gap-2.5 rounded-md text-[13.5px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
                <span className="flex w-[18px] justify-center">
                    {failed ? <X className="h-3.5 w-3.5 text-red-600/70 dark:text-red-400/70" strokeWidth={2.25} /> : <Check className="h-3.5 w-3.5 text-muted-foreground/60" strokeWidth={2.25} />}
                </span>
                {count} {count === 1 ? 'action' : 'actions'}
                {open ? <ChevronDown className="h-3 w-3 opacity-60" /> : <ChevronRight className="h-3 w-3 opacity-60" />}
            </button>
            {open && (
                <ol className="tl-open mt-1.5 space-y-1.5 pl-[7px] text-[13px] leading-5">
                    {items.map((item, i) =>
                        item.kind === 'said' ? (
                            <li key={i} className="pl-[22px] text-muted-foreground/80" data-testid="builder-action-said">
                                {item.text}
                            </li>
                        ) : (
                            <Action key={i} step={item.step} />
                        ),
                    )}
                    {legacy.map((line, i) => (
                        <li key={`legacy-${i}`} className="pl-[22px] text-muted-foreground">
                            {line}
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}

const FRESH_MS = 1400;

/** Steps whose change just landed, held a moment so their check draws in; steps done when the view opened stand still. */
function useJustDone(parts: BuilderProgressNode[]): Set<string> {
    const seen = useRef<Map<string, BuilderProgressNode['state']> | null>(null);
    const until = useRef(new Map<string, number>());
    const now = performance.now();
    if (seen.current) {
        for (const part of parts) {
            const before = seen.current.get(part.nodeId);
            if (part.state === 'done' && before && before !== 'done') until.current.set(part.nodeId, now + FRESH_MS);
        }
    }
    seen.current = new Map(parts.map((p) => [p.nodeId, p.state]));
    for (const [id, at] of until.current) if (at < now) until.current.delete(id);
    return new Set(until.current.keys());
}

/** "channel", "channel and message", "channel, message and 2 more". */
function fieldList(part: BuilderProgressNode): string {
    const said = part.fields.map((field) => fieldTitle(part.type, field));
    if (said.length <= 2) return said.join(' and ');
    return `${said.slice(0, 2).join(', ')} and ${said.length - 2} more`;
}

/** What's happening to a step, or what changed. */
function partLine(part: BuilderProgressNode): string {
    if (part.state === 'removed') return 'Removed';
    if (part.state === 'queued') return 'Up next';
    if (part.state === 'active') {
        if (part.currentField) return `Setting ${fieldTitle(part.type, part.currentField)}`;
        return part.change === 'added' ? 'Adding it' : 'Changing it';
    }
    if (part.change === 'added') return part.fields.length ? `Added · set ${fieldList(part)}` : 'Added';
    return part.fields.length ? `Changed ${fieldList(part)}` : 'Changed';
}

/** A step by its label; one only the builder's handle names is called by its app. */
const nameOf = (part: BuilderProgressNode) => (part.label !== part.nodeId ? part.label : (part.type && getNodeIconMeta(part.type)?.label) || part.label);

/** The steps a turn touched, one row each; a row opens its step on the canvas. */
export function BuilderParts({ parts, workflowId, frozen }: { parts: BuilderProgressNode[]; workflowId?: string; /** Stopped or failed: nothing is at work. */ frozen?: boolean }) {
    useFieldTitles(parts.map((part) => part.type));
    const fresh = useJustDone(parts);
    return (
        <ul className="flex flex-col" data-testid="builder-parts">
            {parts.map((part) => {
                const removed = part.state === 'removed';
                const canOpen = !!workflowId && !removed;
                return (
                    <li key={part.nodeId}>
                        <button
                            type="button"
                            disabled={!canOpen}
                            onClick={() => workflowId && navigateToNode(workflowId, part.nodeId)}
                            title={canOpen ? 'Show on the canvas' : undefined}
                            className="-mx-2 flex min-h-[46px] w-[calc(100%+1rem)] items-center gap-3 rounded-xl px-2 py-1.5 text-left transition-colors enabled:hover:bg-foreground/[0.04] disabled:cursor-default"
                        >
                            <NodeMark type={part.type ?? ''} size="sm" className={cn('transition-[filter,opacity] duration-500', (part.state === 'queued' || removed) && 'opacity-50 grayscale')} />
                            <span className="min-w-0 flex-1">
                                <span className={cn('block truncate text-[14px] leading-5', removed ? 'text-muted-foreground line-through decoration-foreground/30' : 'text-foreground')}>{nameOf(part)}</span>
                                <span className="block truncate text-[12.5px] leading-[18px] text-muted-foreground">{partLine(part)}</span>
                            </span>
                            <span className="flex h-5 min-w-[20px] shrink-0 items-center justify-end">
                                {part.state === 'active' && !frozen ? (
                                    <ThinkingOrb state="shaping" size={20} style={{ width: 18, height: 18 }} aria-label={partLine(part)} />
                                ) : part.state === 'done' ? (
                                    fresh.has(part.nodeId) ? <FreshCheck check="draw" /> : <Check className="h-3.5 w-3.5 text-muted-foreground/70" strokeWidth={2.5} />
                                ) : part.state === 'removed' ? null : (
                                    <span className="h-1.5 w-1.5 rounded-full bg-foreground/25" />
                                )}
                            </span>
                        </button>
                    </li>
                );
            })}
        </ul>
    );
}
