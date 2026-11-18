import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { cn } from '@/ui/utils';
import { userLabel } from '@/screens/console/lib/userFilter';
import { UserPickerList } from './UserFacet';

/**
 * A write form's explicit User: who the call acts for and bills. Only this
 * field sends the NoClick-User header; it starts at `defaultWriteUser(filter)`,
 * never silently at the page filter. Suspended users can't be chosen.
 */
export function UserField({
    value,
    onChange,
    label = 'User',
    disabled = false,
    className,
}: {
    /** Your id for the user; null = your account. */
    value: string | null;
    onChange: (value: string | null) => void;
    label?: string;
    disabled?: boolean;
    className?: string;
}) {
    const [open, setOpen] = useState(false);
    return (
        <div className={cn('flex flex-col gap-1.5', className)}>
            <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    disabled={disabled}
                    aria-label={label}
                    className="inline-flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-left text-[13px] text-foreground disabled:opacity-50"
                >
                    <span className={cn('truncate', value ? 'text-foreground/85' : 'text-muted-foreground')}>{userLabel(value)}</span>
                    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                </PopoverTrigger>
                <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] min-w-[16rem] p-1.5">
                    {open && (
                        <UserPickerList
                            selected={value}
                            disableSuspended
                            fixed={[{ value: null, label: 'Your account' }]}
                            onPick={(v) => {
                                onChange(v);
                                setOpen(false);
                            }}
                        />
                    )}
                </PopoverContent>
            </Popover>
        </div>
    );
}
