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
            className={`group/lock inline-flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap rounded-full text-[12.5px] transition-colors duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${iconOnly ? 'h-7 w-7' : 'h-8 gap-2 pl-2.5 pr-3.5'} ${disabled ? 'cursor-not-allowed opacity-60' : ''} ${locked ? 'bg-foreground/[0.1] font-medium text-foreground ring-1 ring-inset ring-foreground/[0.14] hover:bg-foreground/[0.14]' : `text-muted-foreground hover:bg-foreground/[0.08] hover:text-foreground ${iconOnly ? '' : 'bg-foreground/[0.04]'}`}`}
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
