/* Chrome shared across the onboarding variants: the step counter and the
   trigger→agent→tools graph. The phase content itself lives in phases.tsx —
   this file only holds what wraps around it. Laid out with flex rather than
   absolute pixels so the graph survives any container width. */

import { AlertTriangle, Sparkles } from 'lucide-react';
import { motion } from 'framer-motion';
import { LogoMark } from '~/components/shared/LogoMark';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { cn } from '~/lib/utils';
import type { CredentialStep } from './types';

/** Persistent identity for the flow — you should never lose track of which
    agent you are setting up. The breathing orb is the same mark every other
    AI-activity surface uses, so the thing being built reads as alive. Set in
    the UI sans (Inter) rather than the brand face: at this size the geometric
    display face is heavier than a wayfinding header wants to be. */
export function SetupHeader({ className, name }: { className?: string; name?: string }) {
    return (
        <div className={cn('flex items-center gap-3.5', className)}>
            {/* thinking-orbs only has presets for size 20 and 64 — any other
                value throws out of resolvePreset and takes the render down with
                it. Draw the 64px preset and let CSS scale it to fit the title. */}
            <ThinkingOrb
                state="breathing"
                size={64}
                aria-label=""
                style={{ width: 34, height: 34 }}
            />
            <h1 className="mb-0 font-sans text-[30px] font-semibold leading-[1.1] tracking-[-0.03em]">
                {name ?? 'Your agent'}
            </h1>
        </div>
    );
}

export function Mark({
    iconHtml,
    iconColor,
    iconNode,
    size = 'md',
    fallback,
}: {
    iconHtml: string;
    iconColor?: string;
    /** Ready icon element — wins over iconHtml; the client-registry path. */
    iconNode?: React.ReactNode;
    size?: 'sm' | 'md' | 'lg';
    fallback?: string;
}) {
    const box = size === 'sm' ? 'h-8 w-8' : size === 'md' ? 'h-10 w-10' : 'h-14 w-14';
    const glyph = size === 'sm' ? 'h-4 w-4' : size === 'md' ? 'h-5 w-5' : 'h-7 w-7';
    return (
        <div
            className={cn(
                'grid shrink-0 place-items-center rounded-xl border border-foreground/10 bg-foreground/[0.04]',
                box
            )}
        >
            {iconNode ? (
                <span className={cn(glyph, 'inline-flex')}>{iconNode}</span>
            ) : iconHtml ? (
                <SerializedIcon html={iconHtml} iconColor={iconColor} className={glyph} />
            ) : (
                <Sparkles className={cn(glyph, 'text-foreground/50')} />
            )}
            {!iconHtml && fallback ? <span className="sr-only">{fallback}</span> : null}
        </div>
    );
}

/** Product mark, top-left. Fixed so it stays put as phases change width. */
export function BrandCorner() {
    return (
        <div className="pointer-events-none fixed left-7 top-7 z-40">
            <LogoMark className="h-6 w-6 opacity-70" />
        </div>
    );
}

export function StepProgress({ step, total }: { step: number; total: number }) {
    return (
        <div className="flex items-center gap-3">
            <div className="h-1 w-full max-w-[180px] overflow-hidden rounded-full bg-foreground/10">
                <motion.i
                    className="block h-full rounded-full bg-foreground/45"
                    initial={false}
                    animate={{ width: `${((step + 1) / total) * 100}%` }}
                    transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                />
            </div>
            <span className="shrink-0 text-[12px] tabular-nums text-foreground/35">
                Step {step + 1} of {total}
            </span>
        </div>
    );
}

/** Mirrors the real canvas: trigger feeds the agent, tools hang underneath. */
export function AgentGraph({
    steps,
    active,
    className,
}: {
    steps: CredentialStep[];
    active?: string;
    className?: string;
}) {
    const trigger = steps.find((s) => s.id === 'automation-gmail');
    const providers = steps.filter((s) => s.id !== trigger?.id);
    const toolCount = steps.reduce((n, s) => n + s.tools.length, 0);

    const card = (highlighted: boolean) =>
        cn(
            'rounded-xl border px-3 py-2.5 transition-all duration-300',
            highlighted
                ? 'border-foreground/40 bg-foreground/[0.08] shadow-[0_0_28px_-8px_hsl(var(--foreground)/0.25)]'
                : 'border-foreground/12 bg-card'
        );

    const NodeCard = ({ step, sub }: { step: CredentialStep; sub: string }) => (
        <div className={cn(card(step.id === active), 'flex min-w-0 flex-1 items-center gap-2.5')}>
            <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-foreground/10 bg-foreground/[0.04]">
                <SerializedIcon html={step.iconHtml} iconColor={step.iconColor} className="h-4 w-4" />
            </div>
            <div className="min-w-0">
                <div className="truncate text-[12.5px] font-medium">{step.label}</div>
                <div className="truncate text-[10.5px] text-foreground/35">{sub}</div>
            </div>
            {step.expectedOutcome === 'failed' && (
                <AlertTriangle className="ml-auto h-3.5 w-3.5 shrink-0 text-red-400" />
            )}
        </div>
    );

    return (
        <div className={cn('w-full', className)}>
            <div className="flex items-stretch gap-2">
                {trigger && <NodeCard step={trigger} sub="trigger" />}
                <div className="flex w-4 shrink-0 items-center" aria-hidden="true">
                    <div className="h-px w-full bg-foreground/20" />
                </div>
                <div className={cn(card(active === 'runtime'), 'min-w-0 flex-1')}>
                    <div className="text-[12.5px] font-medium leading-snug">Lead Response Agent</div>
                    <div className="mt-1.5 text-[10.5px] text-foreground/35">
                        {toolCount} tool{toolCount === 1 ? '' : 's'} allowed
                    </div>
                </div>
            </div>

            {providers.length > 0 && (
                <>
                    <div className="flex justify-end" aria-hidden="true">
                        <div className="mr-[25%] h-5 border-l border-dashed border-foreground/20" />
                    </div>
                    <div className="flex gap-2">
                        {providers.map((p) => (
                            <NodeCard
                                key={p.id}
                                step={p}
                                sub={`${p.tools.length} action${p.tools.length === 1 ? '' : 's'}`}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
