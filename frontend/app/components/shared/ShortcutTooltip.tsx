// Hover tooltip that names its trigger. The keyboard shortcut a caller passes still
// works but is never shown: no keycaps in tooltips, as nowhere else in the app.
// Wraps the shared Radix tooltip primitives (self-contained provider, matching the
// pattern used elsewhere) and styles the surface like the command palette.
// `asChild` lets it decorate any focusable trigger without adding wrapper markup.
import { type ReactNode } from 'react';
import {
    Tooltip,
    TooltipTrigger,
    TooltipContent,
    TooltipProvider,
} from '~/components/ui/tooltip';

/** The app's tooltip surface (the sidebar's, the palette's): any tooltip that isn't a ShortcutTooltip wears it too. */
export const TOOLTIP_SURFACE = 'border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] text-xs text-foreground shadow-xl dark:shadow-black/60';

export function ShortcutTooltip({
    label,
    side = 'bottom',
    sideOffset,
    children,
}: {
    /** Omit when the trigger already shows its name: then it has no tooltip. */
    label?: string;
    /** The trigger's shortcut, kept beside it in the code; never shown. */
    keys?: string[];
    sequence?: boolean;
    side?: 'top' | 'bottom' | 'left' | 'right';
    /** Distance from the trigger — bump it for triggers wrapped in a padded
     *  container so the visible gap matches plain buttons. */
    sideOffset?: number;
    children: ReactNode;
}) {
    // Nothing to show: the trigger bare rather than an empty floating box.
    if (!label) {
        return <>{children}</>;
    }
    return (
        <TooltipProvider delayDuration={300}>
            <Tooltip>
                <TooltipTrigger asChild>{children}</TooltipTrigger>
                <TooltipContent
                    side={side}
                    sideOffset={sideOffset}
                    className={`flex max-w-[min(32rem,var(--radix-tooltip-content-available-width))] items-center gap-2 ${TOOLTIP_SURFACE}`}
                >
                    {/* A long label (a whole command or path) wraps inside the width it has. */}
                    <span className="min-w-0 [overflow-wrap:anywhere]">{label}</span>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
