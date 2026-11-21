// Friendly date / date-time field for config values.
// Wraps DroppableTextField (so users keep typing + dropping {{references}}) and adds
// a calendar picker popover with quick presets, mirroring how Make/Zapier let
// users pick a date without hand-writing it.
//
// mode="datetime" (default): stores UTC ISO 8601 (…Z), input type=datetime-local.
// mode="date": stores a plain YYYY-MM-DD calendar date (no time / no TZ shift),
//   input type=date — used for APIs whose fields are date-only (e.g. Pipedrive
//   expected_close_date / start_date / end_date).

import { useState, useRef, useEffect } from 'react';
import { DroppableTextField, containsReferences } from './DroppableTextField';

const pad = (n: number) => String(n).padStart(2, '0');

// UTC ISO (or any parseable value) → local "YYYY-MM-DDTHH:mm:ss" for datetime-local.
function isoToLocalInputValue(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// A Date → UTC ISO 8601 trimmed to seconds (YYYY-MM-DDTHH:MM:SSZ).
function dateToIso(d: Date): string {
    return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

// A Date → local calendar date "YYYY-MM-DD" (no time, no TZ conversion).
function dateToYmd(d: Date): string {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const YMD_RE = /^\d{4}-\d{2}-\d{2}$/;

function humanReadable(iso: string, dateOnly: boolean): string | null {
    const d = new Date(dateOnly && YMD_RE.test(iso) ? `${iso}T00:00:00` : iso);
    if (isNaN(d.getTime())) return null;
    return d.toLocaleString(undefined, dateOnly ? { dateStyle: 'medium' } : { dateStyle: 'medium', timeStyle: 'short' });
}

const datetimePresets: { label: string; get: () => Date }[] = [
    { label: 'Now', get: () => new Date() },
    { label: '+1 hour', get: () => new Date(Date.now() + 3600_000) },
    { label: 'Tomorrow 9 AM', get: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d; } },
    { label: 'Next week', get: () => { const d = new Date(); d.setDate(d.getDate() + 7); d.setHours(9, 0, 0, 0); return d; } },
];
const datePresets: { label: string; get: () => Date }[] = [
    { label: 'Today', get: () => new Date() },
    { label: 'Tomorrow', get: () => { const d = new Date(); d.setDate(d.getDate() + 1); return d; } },
    { label: 'Next week', get: () => { const d = new Date(); d.setDate(d.getDate() + 7); return d; } },
];

const CalendarIcon = () => (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
);

interface DateTimeFieldProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    fieldKey: string;
    hasError?: boolean;
    mode?: 'datetime' | 'date';
}

export function DateTimeField({ value, onChange, placeholder, fieldKey, hasError, mode = 'datetime' }: DateTimeFieldProps) {
    const [open, setOpen] = useState(false);
    const wrapRef = useRef<HTMLDivElement>(null);
    const dateOnly = mode === 'date';

    const strVal = value == null ? '' : String(value);
    const isRef = containsReferences(strVal);
    const human = !isRef && strVal ? humanReadable(strVal, dateOnly) : null;
    const store = (d: Date) => onChange(dateOnly ? dateToYmd(d) : dateToIso(d));
    const presets = dateOnly ? datePresets : datetimePresets;

    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, [open]);

    return (
        <div className="relative" ref={wrapRef}>
            <div className="relative">
                <button
                    type="button"
                    onClick={() => setOpen((o) => !o)}
                    title={dateOnly ? 'Pick a date' : 'Pick a date & time'}
                    aria-label={dateOnly ? 'Pick a date' : 'Pick a date and time'}
                    className={`absolute left-1.5 top-1/2 -translate-y-1/2 z-20 flex items-center justify-center w-7 h-7 rounded-md transition-colors ${
                        open ? 'bg-accent dark:bg-zinc-700 text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-700/70'
                    }`}
                >
                    <CalendarIcon />
                </button>
                <DroppableTextField
                    value={strVal}
                    onChange={onChange}
                    placeholder={placeholder}
                    fieldKey={fieldKey}
                    hasError={hasError}
                    className="pl-10"
                />
            </div>

            {human && (
                <div className="mt-1 text-[11px] text-muted-foreground/70 dark:text-zinc-500">{human}{dateOnly ? '' : <span className="text-muted-foreground/60 dark:text-zinc-600"> · your local time</span>}</div>
            )}

            {open && (
                <div className="absolute z-50 mt-1 left-0 w-72 rounded-lg border border-border dark:border-zinc-700 bg-card p-3 shadow-xl">
                    <label className="block text-[11px] font-medium text-muted-foreground mb-1.5">
                        {dateOnly ? 'Pick date' : <>Pick date &amp; time <span className="text-muted-foreground/60 dark:text-zinc-600">(your local time)</span></>}
                    </label>
                    {dateOnly ? (
                        <input
                            type="date"
                            value={YMD_RE.test(strVal) ? strVal : ''}
                            onChange={(e) => { if (e.target.value) onChange(e.target.value); }}
                            className="w-full px-2 py-1.5 text-sm rounded-md bg-muted border border-border dark:border-zinc-700 text-foreground focus:border-foreground/40 focus:outline-none [color-scheme:light] dark:[color-scheme:dark]"
                        />
                    ) : (
                        <input
                            type="datetime-local"
                            step={1}
                            value={isoToLocalInputValue(strVal)}
                            onChange={(e) => {
                                const v = e.target.value;
                                if (!v) return;
                                const d = new Date(v);
                                if (!isNaN(d.getTime())) onChange(dateToIso(d));
                            }}
                            className="w-full px-2 py-1.5 text-sm rounded-md bg-muted border border-border dark:border-zinc-700 text-foreground focus:border-foreground/40 focus:outline-none [color-scheme:light] dark:[color-scheme:dark]"
                        />
                    )}
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {presets.map((p) => (
                            <button
                                key={p.label}
                                type="button"
                                onClick={() => store(p.get())}
                                className="px-2 py-0.5 text-[11px] rounded-full bg-secondary border border-border dark:border-zinc-700 text-muted-foreground dark:text-zinc-300 hover:bg-accent dark:hover:bg-zinc-700 hover:text-foreground transition-colors"
                            >
                                {p.label}
                            </button>
                        ))}
                    </div>
                    <div className="mt-2.5 text-[10px] leading-relaxed text-muted-foreground/70 dark:text-zinc-500">
                        {dateOnly
                            ? 'Stored as a calendar date (YYYY-MM-DD). You can also type a value or drop a reference.'
                            : 'Stored as UTC ISO 8601 (…Z). You can also type a value or drop a reference from another node.'}
                    </div>
                </div>
            )}
        </div>
    );
}
