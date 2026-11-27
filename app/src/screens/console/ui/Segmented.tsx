import type { ReactNode } from 'react';
import { cn } from '@/ui/utils';

export interface SegmentedOption<T extends string> {
    value: T;
    label: ReactNode;
}

/** A small exclusive toggle on one pill track (`Live · All · Failed`, `Key · User · Agent · Type`); `fill` spreads it
 *  across its row, as a form's choice of kind (`Secret · Publishable`). */
export function Segmented<T extends string>({
    options,
    value,
    onChange,
    label,
    fill = false,
    className,
}: {
    options: readonly SegmentedOption<T>[];
    value: string | null;
    onChange: (value: T) => void;
    label?: string;
    fill?: boolean;
    className?: string;
}) {
    return (
        <div
            role="group"
            aria-label={label}
            className={cn('items-center rounded-full bg-secondary p-0.5 dark:bg-foreground/[0.05]', fill ? 'flex h-10 w-full p-1' : 'inline-flex h-8', className)}
        >
            {options.map((opt) => (
                <button
                    key={opt.value}
                    type="button"
                    aria-pressed={value === opt.value}
                    onClick={() => onChange(opt.value)}
                    className={cn(
                        'rounded-full px-3 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                        fill ? 'h-8 min-w-0 flex-1 text-[13px]' : 'h-7 text-xs',
                        value === opt.value ? 'bg-background text-foreground shadow-sm dark:bg-foreground/[0.12] dark:shadow-none' : 'text-foreground/70 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground'
                    )}
                >
                    {opt.label}
                </button>
            ))}
        </div>
    );
}
