import { ChevronDown } from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';

export interface FacetOption {
    value: string;
    label: string;
}

const ANY = '__any__';

/** A sentence facet, "Status: **Any** ▾". On query-bar pages it writes a token, not its own param. */
export function FacetSelect({
    label,
    value,
    options,
    onChange,
    anyLabel = 'Any',
    className,
}: {
    label: string;
    value: string | null;
    options: readonly FacetOption[];
    onChange: (value: string | null) => void;
    /** The "no filter" choice; pass null to require a value. */
    anyLabel?: string | null;
    className?: string;
}) {
    const current = options.find((o) => o.value === value)?.label ?? value ?? anyLabel ?? '';
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                className={cn(
                    'inline-flex h-8 items-center gap-1 rounded-full bg-secondary hover:bg-accent dark:bg-foreground/[0.05] dark:hover:bg-foreground/[0.09] px-3.5 text-xs text-foreground/70 transition-colors dark:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    className
                )}
            >
                {label}: <span className="font-medium text-foreground">{current}</span>
                <ChevronDown className="h-3.5 w-3.5" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-[10rem]">
                <DropdownMenuRadioGroup value={value ?? ANY} onValueChange={(v) => onChange(v === ANY ? null : v)}>
                    {anyLabel !== null && (
                        <DropdownMenuRadioItem value={ANY} className="text-[13px]">
                            {anyLabel}
                        </DropdownMenuRadioItem>
                    )}
                    {options.map((o) => (
                        <DropdownMenuRadioItem key={o.value} value={o.value} className="text-[13px]">
                            {o.label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
