// A form's dropdown: the app's own (Radix's select on the menus' surface), never the browser's. A field-shaped trigger
// that stands on its own under its label, its list above dialogs (the menus' layer), options in groups where they
// have them. An empty value is a choice like any other ("None"), which Radix's own items can't hold.
import type { ReactNode } from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import { MENU_SURFACE } from '@/ui/menus';
import { cn } from '@/ui/utils';

export interface FieldOption {
    value: string;
    label: ReactNode;
    /** The group heading it sits under, in the order groups first appear. */
    group?: string;
    disabled?: boolean;
}

/** The trigger, as tall and round as the console's fields; `className` sizes it otherwise. */
export const SELECT_TRIGGER =
    'inline-flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-left text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground';

// Radix keeps "" for "nothing chosen", so a "" option travels as this.
const EMPTY = '\u0000empty';
const wire = (value: string) => (value === '' ? EMPTY : value);
const unwire = (value: string) => (value === EMPTY ? '' : value);

export function FieldSelect({
    value,
    onValueChange,
    options,
    placeholder,
    id,
    disabled,
    className,
    'aria-label': ariaLabel,
    'aria-describedby': describedBy,
}: {
    value: string;
    onValueChange: (value: string) => void;
    options: readonly FieldOption[];
    /** Shown while no option holds `value`. */
    placeholder?: string;
    id?: string;
    disabled?: boolean;
    className?: string;
    'aria-label'?: string;
    'aria-describedby'?: string;
}) {
    const chosen = options.some((o) => o.value === value);
    const groups = [...new Set(options.map((o) => o.group))];
    const item = (o: FieldOption) => (
        <SelectPrimitive.Item
            key={o.value}
            value={wire(o.value)}
            disabled={o.disabled}
            className="relative flex w-full cursor-default select-none items-center rounded-md py-1.5 pl-7 pr-2.5 text-[13px] text-foreground outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-foreground/[0.06] data-[disabled]:opacity-50"
        >
            <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                <SelectPrimitive.ItemIndicator>
                    <Check className="h-3.5 w-3.5" />
                </SelectPrimitive.ItemIndicator>
            </span>
            <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
        </SelectPrimitive.Item>
    );
    return (
        <SelectPrimitive.Root value={chosen ? wire(value) : ''} onValueChange={(next) => onValueChange(unwire(next))} disabled={disabled}>
            <SelectPrimitive.Trigger id={id} aria-label={ariaLabel} aria-describedby={describedBy} className={cn(SELECT_TRIGGER, className)}>
                <span className="min-w-0 truncate">
                    <SelectPrimitive.Value placeholder={placeholder ?? 'Choose'} />
                </span>
                <SelectPrimitive.Icon asChild>
                    <ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                </SelectPrimitive.Icon>
            </SelectPrimitive.Trigger>
            <SelectPrimitive.Portal>
                <SelectPrimitive.Content
                    position="popper"
                    sideOffset={4}
                    className={cn(
                        'z-[80] max-h-[min(22rem,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl p-1.5',
                        MENU_SURFACE
                    )}
                >
                    <SelectPrimitive.Viewport>
                        {groups.map((group) =>
                            group === undefined ? (
                                options.filter((o) => o.group === undefined).map(item)
                            ) : (
                                <SelectPrimitive.Group key={group}>
                                    <SelectPrimitive.Label className="px-2.5 pb-1 pt-2 text-[11.5px] font-medium text-muted-foreground">{group}</SelectPrimitive.Label>
                                    {options.filter((o) => o.group === group).map(item)}
                                </SelectPrimitive.Group>
                            )
                        )}
                    </SelectPrimitive.Viewport>
                </SelectPrimitive.Content>
            </SelectPrimitive.Portal>
        </SelectPrimitive.Root>
    );
}
