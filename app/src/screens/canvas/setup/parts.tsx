// What wraps a step of the Setup tab: the name of what's being set up, how far along it is, and a step's mark. The
// steps themselves are in SetupView.tsx and AccountStep.tsx.
import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
import { useSlot } from '@/slots';
import { SerializedIcon } from '@/ui/SerializedIcon';
import { cn } from '@/ui/utils';
import { SETUP } from '../slots';

/** Which workflow this is, kept in view on every step. Set in the UI sans rather than the brand face: at this size
 *  the display face is heavier than a wayfinding header wants to be. */
export function SetupHeader({ className, name }: { className?: string; name?: string }) {
    const { Orb } = useSlot(SETUP);
    return (
        <div className={cn('flex items-center gap-3.5', className)}>
            <Orb />
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
    /** A ready glyph: wins over `iconHtml`. */
    iconNode?: ReactNode;
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
