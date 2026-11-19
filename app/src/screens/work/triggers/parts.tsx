// The small pieces a trigger's setup is made of, the same when adding one and changing it: pill choices, a value with
// Copy, a field's label, the schedule in plain words (read back, its next runs, its clock) and "Then it should".
import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ChevronDown, Clock, Copy } from 'lucide-react';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { longWhen, readSchedule } from './model';

export const PILL = 'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-colors max-sm:h-9 max-sm:text-[13.5px]';
export const PILL_OFF = 'bg-foreground/[0.05] text-foreground/80 hover:bg-foreground/[0.09] hover:text-foreground';
export const PILL_ON = 'bg-foreground text-background';
export const LABEL = 'mb-1.5 block text-[12.5px] font-medium text-muted-foreground';
export const FIELD = 'flex h-10 w-full items-center gap-2 rounded-full border border-border bg-transparent px-4 text-[14px] transition-colors focus-within:border-foreground/30 dark:border-foreground/[0.12] dark:focus-within:border-foreground/30';
export const INPUT = 'min-w-0 flex-1 bg-transparent outline-none placeholder:text-[hsl(var(--placeholder))] max-sm:text-[16px]';
export const NOTE = 'mt-1.5 px-1 text-[12.5px] leading-snug text-muted-foreground';

export function Pills<T extends string>({ value, options, onChange, disabled }: { value: T | undefined; options: { id: T; label: ReactNode }[]; onChange: (v: T) => void; disabled?: boolean }) {
    return (
        <div className="flex flex-wrap gap-1.5">
            {options.map((o) => (
                <button key={o.id} type="button" disabled={disabled} aria-pressed={value === o.id} onClick={() => onChange(o.id)} className={cn(PILL, value === o.id ? PILL_ON : PILL_OFF, 'disabled:opacity-50')}>
                    {o.label}
                </button>
            ))}
        </div>
    );
}

export function Copyable({ value, label, block = false }: { value: string; label: string; block?: boolean }) {
    const copy = () => {
        void navigator.clipboard?.writeText(value).then(
            () => toast(`${label} copied`),
            () => toast(`Couldn’t copy ${label.toLowerCase()}`)
        );
    };
    if (block)
        return (
            <div className="relative rounded-[18px] bg-foreground/[0.05] p-3.5 pr-20">
                <pre className="whitespace-pre-wrap break-all font-mono text-[12px] leading-relaxed text-foreground/85">{value}</pre>
                <button type="button" onClick={copy} aria-label={`Copy ${label.toLowerCase()}`} className={cn(BUTTON_SECONDARY, 'absolute right-2 top-2 h-7 gap-1 px-2.5 text-[12px]')}>
                    <Copy className="h-3 w-3" strokeWidth={2} />
                    Copy
                </button>
            </div>
        );
    return (
        <div className="flex h-10 items-center gap-2 rounded-full bg-foreground/[0.05] pl-4 pr-1.5">
            <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{value}</span>
            <button type="button" onClick={copy} aria-label={`Copy ${label.toLowerCase()}`} className={cn(BUTTON_SECONDARY, 'h-7 gap-1 px-2.5 text-[12px]')}>
                <Copy className="h-3 w-3" strokeWidth={2} />
                Copy
            </button>
        </div>
    );
}

/** Your time: this browser's clock, by name. (The API's `user` follows an agent's user, and the account's agents
 *  have none, so a schedule set here names the zone.) */
export const localZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const OTHER_ZONES = ['UTC', 'America/New_York', 'Europe/London', 'Asia/Kolkata', 'Asia/Singapore', 'Australia/Sydney'];
const zoneLabel = (tz: string) => (tz === localZone() ? `your time (${tz})` : tz);

/** A schedule in plain words: the box, ideas while it's empty, then what it reads as, what it assumed, its next runs and
 *  its clock; or how to say it. */
export function ScheduleField({ words, onWords, tz, onTz, focusFirst }: { words: string; onWords: (words: string) => void; tz: string; onTz: (tz: string) => void; focusFirst?: boolean }) {
    const s = readSchedule(words);
    const [zones, setZones] = useState(false);
    return (
        <div className="flex flex-col gap-2">
            <label className="block">
                <span className={LABEL}>When, in plain words</span>
                <span className={FIELD}>
                    <Clock className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
                    {/* eslint-disable-next-line jsx-a11y/no-autofocus -- it opens to say when */}
                    <input autoFocus={focusFirst} value={words} onChange={(e) => onWords(e.target.value)} placeholder="every weekday at 9" aria-label="When" className={INPUT} />
                </span>
            </label>
            {!words.trim() ? (
                <div className="flex flex-wrap gap-1.5">
                    {['every weekday at 9', 'every hour', 'mondays at 8:30am', 'every month on the 1st at 9'].map((x) => (
                        <button key={x} type="button" onClick={() => onWords(x)} className={cn(PILL, PILL_OFF)}>
                            {x}
                        </button>
                    ))}
                </div>
            ) : (
                <div className="rounded-[20px] bg-foreground/[0.03] p-3.5 ring-1 ring-inset ring-border dark:ring-foreground/[0.07]" data-testid="schedule-read">
                    {s ? (
                        <>
                            <p className="text-[14px] font-medium">{s.words}</p>
                            {s.assumed && <p className="text-[12.5px] text-muted-foreground">At {s.assumed}, since you didn’t say.</p>}
                            {tz === localZone() && (
                                <>
                                    <p className="mb-1.5 mt-2.5 text-[12px] text-muted-foreground">Its next runs</p>
                                    <div className="flex flex-wrap gap-1.5">
                                        {s.next(3).map((d) => (
                                            <span key={d.toISOString()} className="inline-flex h-7 items-center rounded-full bg-foreground/[0.06] px-2.5 text-[12.5px] tabular-nums">
                                                {longWhen(d).replace(/^\w/, (c) => c.toUpperCase())}
                                            </span>
                                        ))}
                                    </div>
                                </>
                            )}
                            <div className="mt-3 flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                                <span>In</span>
                                <button type="button" aria-expanded={zones} onClick={() => setZones((z) => !z)} className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-foreground/85 hover:bg-foreground/[0.06]">
                                    {zoneLabel(tz)}
                                    <ChevronDown className="h-3 w-3" strokeWidth={2} />
                                </button>
                            </div>
                            {zones && (
                                <div className="mt-2">
                                    <Pills
                                        value={tz}
                                        options={[localZone(), ...OTHER_ZONES.filter((z) => z !== localZone())].map((z) => ({ id: z, label: z === localZone() ? 'Your time' : z }))}
                                        onChange={(z) => {
                                            onTz(z);
                                            setZones(false);
                                        }}
                                    />
                                </div>
                            )}
                        </>
                    ) : (
                        <p className="text-[13px] leading-snug text-muted-foreground">I can’t read that one yet. Try “every weekday at 9”, “mondays and thursdays at 8:30am” or “every 15 minutes”.</p>
                    )}
                </div>
            )}
        </div>
    );
}

/** What it's told each time it wakes. */
export function ThenField({ value, onChange, placeholder, label = 'Then it should' }: { value: string; onChange: (v: string) => void; placeholder: string; label?: string }) {
    return (
        <label className="block">
            <span className={LABEL}>{label}</span>
            <textarea
                value={value}
                onChange={(e) => onChange(e.target.value)}
                rows={2}
                placeholder={placeholder}
                className="block w-full resize-none rounded-[26px] border border-border bg-transparent px-4 py-3 text-[14px] leading-snug outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/30 dark:border-foreground/[0.12] max-sm:text-[16px]"
            />
        </label>
    );
}
