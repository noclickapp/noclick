// Shared credential approval control for connection settings and workflow tools.
// Its state describes whether calls require approval, independently of tool selection.
import { HiOutlineLockClosed, HiOutlineLockOpen } from 'react-icons/hi2';
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '~/components/ui/tooltip';

export function CredentialRuleLock({
    name,
    locked,
    disabled,
    busy,
    saving,
    iconOnly,
    onChange,
}: {
    name: string;
    locked: boolean;
    disabled?: boolean;
    busy?: boolean;
    saving?: boolean;
    iconOnly?: boolean;
    onChange: () => void;
}) {
    const hint = `${locked ? 'Approval required' : 'No approval needed'}${disabled ? '' : locked ? ' · Click to unlock' : ' · Click to lock'}`;
    const button = (
        <button
            type="button"
            aria-label={`Require approval for ${name}`}
            aria-pressed={locked}
            title={iconOnly ? undefined : hint}
            disabled={disabled}
            aria-disabled={disabled || busy || undefined}
            aria-busy={saving || undefined}
            onClick={() => {
                if (!disabled && !busy) onChange();
            }}
            className={`group/lock inline-flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap rounded-md text-xs transition-colors duration-150 motion-reduce:transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring ${iconOnly ? 'h-7 w-7' : 'h-8 gap-2 px-2.5'} ${disabled ? 'cursor-not-allowed opacity-60' : ''} ${!iconOnly && !locked ? 'bg-foreground/[0.04]' : ''} ${locked ? 'bg-amber-500/[0.08] text-amber-600 hover:bg-amber-500/[0.14] dark:text-amber-400' : 'text-muted-foreground hover:bg-foreground/[0.08] hover:text-foreground'}`}
        >
            <span
                aria-hidden="true"
                className="relative h-[18px] w-[18px] shrink-0"
            >
                <HiOutlineLockClosed
                    className={`absolute inset-0 h-full w-full transition-opacity duration-150 motion-reduce:transition-none ${locked ? 'opacity-100' : 'opacity-0'}`}
                />
                <HiOutlineLockOpen
                    className={`absolute inset-0 h-full w-full transition-opacity duration-150 motion-reduce:transition-none ${locked ? 'opacity-0' : 'opacity-100'}`}
                />
            </span>
            {/* Reserve the longest label's width in every state, including hover. */}
            {!iconOnly && (
                <span className="grid after:invisible after:col-start-1 after:row-start-1 after:content-['Approval_required']">
                    <span className="col-start-1 row-start-1 group-hover/lock:invisible group-focus-visible/lock:invisible">
                        {locked ? 'Approval required' : 'Unlocked'}
                    </span>
                    <span
                        aria-hidden="true"
                        className="invisible col-start-1 row-start-1 group-hover/lock:visible group-focus-visible/lock:visible"
                    >
                        {locked ? 'Unlock' : 'Lock'}
                    </span>
                </span>
            )}
        </button>
    );
    return iconOnly ? (
        <Tooltip>
            <TooltipTrigger asChild>{button}</TooltipTrigger>
            <TooltipContent side="left" className="text-xs">
                {hint}
            </TooltipContent>
        </Tooltip>
    ) : (
        button
    );
}
