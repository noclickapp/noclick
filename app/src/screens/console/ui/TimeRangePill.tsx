import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { LiveDot } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { formatAbsolute } from '@/screens/console/lib/format';
import { ConsoleButton } from './Button';

export interface TimeRange {
    /** A preset (`1h`, `1d`, `1w`, `30d`) or an ISO time; null = no lower bound. */
    since: string | null;
    until: string | null;
}

export const TIME_PRESETS = [
    { value: '1h', label: 'Last hour' },
    { value: '1d', label: 'Last day' },
    { value: '1w', label: 'Last week' },
    { value: '30d', label: 'Last 30 days' },
] as const;

function rangeLabel({ since, until }: TimeRange): string {
    const preset = TIME_PRESETS.find((p) => p.value === since);
    if (preset && !until) return preset.label;
    if (!since && !until) return 'All time';
    const fmt = (v: string) => formatAbsolute(v).replace(/, \d\d:\d\d:\d\d$/, '');
    return `${since ? fmt(since) : '…'} – ${until ? fmt(until) : 'now'}`;
}

/** `<input type="datetime-local">` value ↔ ISO. */
function toLocalInput(iso: string | null): string {
    // Presets (`1d`) aren't times; Date.parse rejects them.
    const t = iso && !/^\d+[mhdw]$/.test(iso) ? Date.parse(iso) : NaN;
    if (Number.isNaN(t)) return '';
    const d = new Date(t - new Date(t).getTimezoneOffset() * 60_000);
    return d.toISOString().slice(0, 16);
}

/**
 * The time range. The pinging live dot shows here, and only when the range
 * ends at now and the page is polling: the one animated dot a page may have.
 */
export function TimeRangePill({ value, onChange, live = false, className }: { value: TimeRange; onChange: (range: TimeRange) => void; live?: boolean; className?: string }) {
    const [open, setOpen] = useState(false);
    const [from, setFrom] = useState(toLocalInput(value.since));
    const [to, setTo] = useState(toLocalInput(value.until));
    const pick = (range: TimeRange) => {
        onChange(range);
        setOpen(false);
    };
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                className={cn(
                    'inline-flex h-8 items-center gap-1.5 rounded-full bg-secondary px-3.5 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:bg-foreground/[0.05] dark:hover:bg-foreground/[0.09]',
                    className
                )}
            >
                {live && !value.until && <LiveDot />}
                <span className="whitespace-nowrap">{rangeLabel(value)}</span>
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-64 p-1.5">
                <div className="flex flex-col">
                    {TIME_PRESETS.map((p) => (
                        <button
                            key={p.value}
                            type="button"
                            aria-pressed={value.since === p.value && !value.until}
                            onClick={() => pick({ since: p.value, until: null })}
                            className="rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-foreground/[0.05] aria-pressed:font-medium"
                        >
                            {p.label}
                        </button>
                    ))}
                    <button type="button" onClick={() => pick({ since: null, until: null })} className="rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-foreground/[0.05]">
                        All time
                    </button>
                    <div className="mt-1 flex flex-col gap-1.5 border-t border-border px-2 pb-1 pt-2">
                        <span className="text-[12px] font-medium text-muted-foreground">Custom</span>
                        <input type="datetime-local" aria-label="From" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 rounded-md border border-input bg-background px-2 text-[12px]" />
                        <input type="datetime-local" aria-label="To" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 rounded-md border border-input bg-background px-2 text-[12px]" />
                        <ConsoleButton
                            size="sm"
                            disabled={!from}
                            onClick={() => pick({ since: new Date(from).toISOString(), until: to ? new Date(to).toISOString() : null })}
                        >
                            Apply
                        </ConsoleButton>
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    );
}
