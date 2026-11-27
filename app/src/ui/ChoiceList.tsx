// One choice out of a few, each a row: its name and a line saying what it does, the app's own round mark on the left,
// the whole row the target. No card around them: the rows stand on their own, as a form's fields do.
import type { ReactNode } from 'react';
import * as RadioGroup from '@radix-ui/react-radio-group';
import { cn } from '@/ui/utils';

export interface Choice<T extends string> {
    value: T;
    label: ReactNode;
    description?: ReactNode;
    disabled?: boolean;
}

export function ChoiceList<T extends string>({
    value,
    onChange,
    options,
    label,
    className,
}: {
    value: T;
    onChange: (value: T) => void;
    options: readonly Choice<T>[];
    /** What the choice is, for a screen reader (the heading above it says it on screen). */
    label: string;
    className?: string;
}) {
    return (
        <RadioGroup.Root value={value} onValueChange={(next) => onChange(next as T)} aria-label={label} className={cn('flex flex-col', className)}>
            {options.map((o) => (
                <RadioGroup.Item
                    key={o.value}
                    value={o.value}
                    disabled={o.disabled}
                    className="group flex w-full items-start gap-3 rounded-xl px-2 py-2.5 text-left outline-none transition-colors hover:bg-foreground/[0.03] focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                    <span
                        aria-hidden
                        className="mt-[3px] grid h-4 w-4 shrink-0 place-items-center rounded-full border border-foreground/30 transition-colors group-data-[state=checked]:border-foreground group-data-[state=checked]:bg-foreground"
                    >
                        <span className="h-1.5 w-1.5 rounded-full bg-background opacity-0 group-data-[state=checked]:opacity-100" />
                    </span>
                    <span className="min-w-0">
                        <span className="block text-[13.5px] font-medium text-foreground">{o.label}</span>
                        {o.description ? <span className="mt-0.5 block text-[12.5px] leading-snug text-muted-foreground">{o.description}</span> : null}
                    </span>
                </RadioGroup.Item>
            ))}
        </RadioGroup.Root>
    );
}
