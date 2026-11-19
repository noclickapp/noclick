// Work's tooltips, on the app's tooltip and its surface, pill-round as the rails' are: `Tip` names an icon-only button;
// `DisabledTip` sits on a button that may be disabled, saying why: a disabled button fires no pointer events, so the
// tooltip hangs off a span around it and the button lets events through. The tree stays the same whether there's a
// label or the button is disabled, so the button never remounts as either changes.
import type { ReactElement, ReactNode } from 'react';
import { TOOLTIP_SURFACE } from '@/ui/ShortcutTooltip';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/ui/tooltip';
import { cn } from '@/ui/utils';

export function DisabledTip({ label, disabled, side = 'bottom', children }: { label: string | null | undefined; disabled: boolean; side?: 'top' | 'bottom' | 'left' | 'right'; children: ReactNode }) {
    return (
        <TooltipProvider delayDuration={300}>
            <Tooltip open={label ? undefined : false}>
                <TooltipTrigger asChild>
                    <span className="inline-flex">
                        <span className={cn('inline-flex', disabled && 'pointer-events-none')}>{children}</span>
                    </span>
                </TooltipTrigger>
                <TooltipContent side={side} className={TOOLTIP_SURFACE}>
                    {label}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}

/** The pill a Work tooltip is drawn as, the rails' own (railTip.tsx). */
const PILL = 'rounded-full px-3 py-1.5 text-[13px] leading-tight';

/** An icon-only button's name, shown on hover and keyboard focus; never a keyboard shortcut. */
export function Tip({ label, side = 'top', children }: { label: string | undefined; side?: 'top' | 'bottom' | 'left' | 'right'; children: ReactElement }) {
    if (!label) return children;
    return (
        <TooltipProvider delayDuration={300}>
            <Tooltip>
                <TooltipTrigger asChild>{children}</TooltipTrigger>
                <TooltipContent side={side} sideOffset={6} className={cn(TOOLTIP_SURFACE, PILL)}>
                    {label}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
