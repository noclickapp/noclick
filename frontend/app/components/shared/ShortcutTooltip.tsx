// Hover tooltip that shows a label plus its keyboard-shortcut keycaps, so leader
// shortcuts are discoverable on toolbar buttons and navbar tabs. Wraps the shared
// Radix tooltip primitives (self-contained provider, matching the pattern used
// elsewhere) and styles the surface like the command palette. `asChild` lets it
// decorate any focusable trigger without adding wrapper markup.
import { type ReactNode } from 'react';
import {
    Tooltip,
    TooltipTrigger,
    TooltipContent,
    TooltipProvider,
} from '~/components/ui/tooltip';
import { KeyHint, SequenceKeyHint } from '~/components/shared/KeyHint';

export function ShortcutTooltip({
    label,
    keys,
    sequence = true,
    side = 'bottom',
    sideOffset,
    children,
}: {
    /** Omit when the trigger already shows its name — then only keycaps render. */
    label?: string;
    /** Keycaps, e.g. ['N','W']. */
    keys?: string[];
    /** True (default) renders "N then W"; false renders a simultaneous combo. */
    sequence?: boolean;
    side?: 'top' | 'bottom' | 'left' | 'right';
    /** Distance from the trigger — bump it for triggers wrapped in a padded
     *  container so the visible gap matches plain buttons. */
    sideOffset?: number;
    children: ReactNode;
}) {
    return (
        <TooltipProvider delayDuration={300}>
            <Tooltip>
                <TooltipTrigger asChild>{children}</TooltipTrigger>
                <TooltipContent
                    side={side}
                    sideOffset={sideOffset}
                    className="flex items-center gap-2 border-white/10 bg-[#0a0a0b] text-xs text-zinc-100 shadow-xl shadow-black/60"
                >
                    {label && <span>{label}</span>}
                    {keys &&
                        keys.length > 0 &&
                        (sequence ? (
                            <SequenceKeyHint keys={keys} />
                        ) : (
                            <KeyHint keys={keys} />
                        ))}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
