// Compact segmented button group (e.g. "7d | 30d | 90d", "Bar | Pie") with
// aria-pressed semantics. Extracted from the usage dashboard, which repeated
// this exact markup for three separate control groups; use it anywhere a
// small exclusive toggle is needed.

import React from 'react';
import { cn } from '~/lib/utils';

export interface SegmentedControlOption<T extends string> {
    value: T;
    label: React.ReactNode;
}

export function SegmentedControl<T extends string>({
    options,
    value,
    onChange,
    className,
    buttonClassName,
}: {
    options: SegmentedControlOption<T>[];
    /** Currently active value. May be a value outside `options` (nothing lights up). */
    value?: string;
    onChange: (value: T) => void;
    className?: string;
    buttonClassName?: string;
}) {
    return (
        <div
            className={cn(
                'flex rounded-lg overflow-hidden border border-white/[0.08] bg-white/[0.02]',
                className
            )}
        >
            {options.map((opt) => (
                <button
                    key={opt.value}
                    type="button"
                    aria-pressed={value === opt.value}
                    onClick={() => onChange(opt.value)}
                    className={cn(
                        'h-8 px-3 text-xs font-medium transition-colors flex items-center justify-center gap-1.5',
                        value === opt.value
                            ? 'bg-white/[0.08] text-white/90'
                            : 'text-white/50 hover:text-white/70 hover:bg-white/[0.04]',
                        buttonClassName
                    )}
                >
                    {opt.label}
                </button>
            ))}
        </div>
    );
}
