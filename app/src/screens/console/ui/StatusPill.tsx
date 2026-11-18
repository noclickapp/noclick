import { cn } from '@/ui/utils';
import type { StatusGlyph, StatusLook } from '@/screens/console/lib/status';

const DOT = 'h-[7px] w-[7px] shrink-0 rounded-full';

/** A small dot: filled for a state reached, a ring for one waiting, green only while running, red only for a failure. */
function Dot({ glyph }: { glyph: StatusGlyph }) {
    switch (glyph) {
        case 'filled':
        case 'check':
            return <span aria-hidden className={cn(DOT, 'bg-foreground/80')} />;
        case 'live':
            // Running right now: the one place the console uses green.
            return <span aria-hidden className={cn(DOT, 'bg-emerald-500')} />;
        case 'waiting':
            return <span aria-hidden className={cn(DOT, 'border-[1.5px] border-foreground/80')} />;
        case 'hollow':
            return <span aria-hidden className={cn(DOT, 'border-[1.5px] border-foreground/50')} />;
        case 'cross':
            return <span aria-hidden className={cn(DOT, 'bg-red-500')} />;
        default:
            return <span aria-hidden className={cn(DOT, 'bg-foreground/25')} />;
    }
}

// The app's rule: a quiet dot and a word, no box; red only for failure.
const TONES = {
    ink: 'text-foreground',
    muted: 'text-foreground/70 dark:text-foreground/60',
    failure: 'text-red-600 dark:text-red-400',
} as const;

/**
 * A status as a dot and a word, with its reason beside it ("Failed · spend
 * cap"). Where a column is narrow, as on a phone, the reason wraps under the
 * word instead of being cut. Never animated.
 */
export function StatusPill({ look, className }: { look: StatusLook; className?: string }) {
    return (
        <span className={cn('inline-flex max-w-full items-start gap-1.5 whitespace-normal text-[13px] font-medium leading-5', TONES[look.tone], className)}>
            <span className="flex h-5 shrink-0 items-center">
                <Dot glyph={look.glyph} />
            </span>
            <span className="min-w-0 break-words">
                {look.label}
                {look.reason ? <span className="font-normal"> · {look.reason}</span> : null}
            </span>
        </span>
    );
}
