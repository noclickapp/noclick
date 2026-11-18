import type { ReactNode } from 'react';
import { cn } from '@/ui/utils';

export interface SegmentedOption<T extends string> {
    value: T;
    label: ReactNode;
}

/** A small exclusive toggle on one pill track (`Live · All · Failed`, `Key · User · Agent · Type`). */
export function Segmented<T extends string>({
    options,
    value,
    onChange,
    label,
    className,
}: {
    options: readonly SegmentedOption<T>[];
    value: string | null;
    onChange: (value: T) => void;
    label?: string;
    className?: string;
}) {
    return (
        <div role="group" aria-label={label} className={cn('inline-flex h-8 items-center rounded-full bg-secondary p-0.5 dark:bg-foreground/[0.05]', className)}>
            {options.map((opt) => (
                <button
                    key={opt.value}
                    type="button"
                    aria-pressed={value === opt.value}
                    onClick={() => onChange(opt.value)}
                    className={cn(
                        'h-7 rounded-full px-3 text-xs font-medium transition-colors',
                        value === opt.value ? 'bg-background text-foreground shadow-sm dark:bg-foreground/[0.12] dark:shadow-none' : 'text-foreground/70 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground'
                    )}
                >
                    {opt.label}
                </button>
            ))}
        </div>
    );
}
