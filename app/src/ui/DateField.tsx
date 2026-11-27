// A form's date, or date and time: a field-shaped button opening the app's calendar, never the browser's picker, and
// with `withTime` an hour and minute typed beside it. Its value is what the browser's own date fields hold, in local
// time: `YYYY-MM-DD`, or `YYYY-MM-DDTHH:MM` with `withTime`, '' for none.
import { useState } from 'react';
import { CalendarDays } from 'lucide-react';
import { Calendar } from '@/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { MENU_SURFACE } from '@/ui/menus';
import { SELECT_TRIGGER } from '@/ui/FieldSelect';
import { cn } from '@/ui/utils';

const pad = (n: number) => String(n).padStart(2, '0');
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const TIME = /^([01]?\d|2[0-3]):([0-5]\d)$/;

/** The day a value names, at local midnight; null for none. */
function dayOf(value: string): Date | null {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
    return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

export function DateField({
    value,
    onChange,
    id,
    placeholder = 'Pick a date',
    withTime = false,
    fromDate,
    toDate,
    className,
    'aria-label': ariaLabel,
}: {
    value: string;
    onChange: (value: string) => void;
    id?: string;
    placeholder?: string;
    withTime?: boolean;
    /** The first and last days it offers. */
    fromDate?: Date;
    toDate?: Date;
    className?: string;
    'aria-label'?: string;
}) {
    const [open, setOpen] = useState(false);
    const day = dayOf(value);
    const timeOf = (v: string) => (/T(\d{2}:\d{2})/.exec(v)?.[1] ?? '');
    const [time, setTime] = useState(timeOf(value) || '09:00');
    const compose = (d: Date, t: string) => (withTime ? `${ymd(d)}T${TIME.test(t) ? t.padStart(5, '0') : '00:00'}` : ymd(d));
    const shown = day ? day.toLocaleDateString(undefined, { dateStyle: 'medium' }) : null;
    return (
        <div className={cn('flex min-w-0 gap-2', className)}>
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger id={id} aria-label={ariaLabel} className={cn(SELECT_TRIGGER, 'justify-start')}>
                    <CalendarDays aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className={cn('min-w-0 flex-1 truncate', !shown && 'text-muted-foreground')}>{shown ?? placeholder}</span>
                </PopoverTrigger>
                <PopoverContent align="start" className={cn('w-auto p-1', MENU_SURFACE)}>
                    <Calendar
                        mode="single"
                        selected={day ?? undefined}
                        defaultMonth={day ?? fromDate}
                        disabled={[...(fromDate ? [{ before: fromDate }] : []), ...(toDate ? [{ after: toDate }] : [])]}
                        onSelect={(picked) => {
                            if (!picked) return;
                            onChange(compose(picked, time));
                            setOpen(false);
                        }}
                        className="bg-transparent"
                    />
                </PopoverContent>
            </Popover>
            {day && !withTime && (
                <button type="button" onClick={() => onChange('')} className="shrink-0 px-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground">
                    Clear
                </button>
            )}
            {withTime && (
                <input
                    aria-label="Time (24-hour)"
                    inputMode="numeric"
                    placeholder="HH:MM"
                    value={time}
                    onChange={(e) => {
                        setTime(e.target.value);
                        if (day && TIME.test(e.target.value)) onChange(compose(day, e.target.value));
                    }}
                    className={cn(SELECT_TRIGGER, 'w-[5.5rem] shrink-0 justify-center text-center tabular-nums')}
                />
            )}
        </div>
    );
}
