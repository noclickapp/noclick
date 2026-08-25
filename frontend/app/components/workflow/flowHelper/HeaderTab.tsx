import type { LucideIcon } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { KeyHint } from '~/components/shared/KeyHint';

type Variant = 'default' | 'warning';

interface HeaderTabProps {
    icon: LucideIcon;
    label: string;
    isActive: boolean;
    /** Collapse the text label to just the icon. */
    isCompact: boolean;
    onClick: () => void;
    disabled?: boolean;
    title: string;
    /** Single-key shortcut shown in the tooltip (e.g. 'C'). */
    shortcut?: string;
    /** 'warning' paints active/hover in red (used by the Credentials tab when
        the selected node has unconnected credentials). */
    variant?: Variant;
    /** data-tour-target hook for the onboarding tour. */
    tourTarget?: string;
}

// Shared center-header tab button. All four header tabs (UX / Nodes / Config /
// Credentials) used near-identical className templates with only the active
// colour, disabled state, and warning variant varying.
export function HeaderTab({
    icon: Icon,
    label,
    isActive,
    isCompact,
    onClick,
    disabled = false,
    title,
    shortcut,
    variant = 'default',
    tourTarget,
}: HeaderTabProps) {
    const isWarning = variant === 'warning';
    const stateClass = isActive
        ? isWarning
            ? 'bg-red-500/20 text-red-600 dark:text-red-400'
            : 'bg-foreground/[0.08] text-foreground'
        : disabled
        ? 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed'
        : isWarning
        ? 'text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 hover:bg-red-500/10'
        : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02]';

    return (
        <TooltipProvider delayDuration={200}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <button
                        data-tour-target={tourTarget}
                        onClick={onClick}
                        disabled={disabled}
                        aria-label={title}
                        className={`flex shrink-0 items-center ${isCompact ? 'gap-1.5 px-2' : 'gap-2 px-3'} py-1.5 rounded-lg text-xs font-medium transition-all ${stateClass}`}
                    >
                        <Icon className="h-3.5 w-3.5" />
                        {!isCompact && <span>{label}</span>}
                    </button>
                </TooltipTrigger>
                {/* Lighter color (kept distinct from the dark canvas-bar tooltips).
                    The tab label is already visible, so the tooltip is just the
                    shortcut keycap (falling back to the title when there's none). */}
                <TooltipContent
                    side="top"
                    sideOffset={8}
                    className="rounded-lg border border-border dark:border-zinc-700/60 bg-popover/95 px-2 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                >
                    {shortcut ? <KeyHint keys={[shortcut]} /> : title}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
