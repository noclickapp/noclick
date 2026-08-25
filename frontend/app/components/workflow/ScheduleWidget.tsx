/**
 * ScheduleWidget - An intuitive schedule picker for cron triggers.
 * Adapts its UI based on the selected frequency to show only relevant options.
 * Pure controlled component — no drag-and-drop (D&D happens at the whole-schedule
 * level in SchedulesWidget instead).
 */

import { useState, useRef, useEffect, useCallback, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';
import { describeSchedule, windowLabel, daysLabel, calendarLabel } from '~/utils/scheduleFormat';

export interface ScheduleConfig {
    frequency: string;
    interval?: number;
    hour?: number;
    minute?: number;
    dayOfWeek?: number;
    dayOfMonth?: number;
    /** Days of week to run on (0=Sunday … 6=Saturday); empty = every day.
     * Entries may arrive as strings (AI-builder XML writes stringify) — the
     * model is Union[int, str]; consumers coerce. */
    daysOfWeek?: (number | string)[];
    /** Part-of-day window, 24h "HH:MM" strings, both-inclusive (e.g. "09:00"–"18:00"). */
    windowStart?: string;
    windowEnd?: string;
    /** Part-of-month range, days 1–31 inclusive; start > end wraps month end. */
    monthDayStart?: number;
    monthDayEnd?: number;
    /** Part-of-year range, months 1–12 inclusive; start > end wraps the new year. */
    monthStart?: number;
    monthEnd?: number;
}

interface ScheduleWidgetProps {
    value: ScheduleConfig;
    onChange: (value: ScheduleConfig) => void;
    /** Frequency values to exclude from the dropdown (e.g., ['seconds']) */
    excludeFrequencies?: string[];
    /** Render the narrowing pills (part of day / days of week / calendar) —
     * enabled where registration honors them (the cron node's
     * SchedulesWidget). */
    showWindow?: boolean;
}

// Frequency options
const FREQUENCY_OPTIONS = [
    { value: 'seconds', label: 'seconds', needsInterval: true, needsTime: false, needsDay: false },
    { value: 'minutes', label: 'minutes', needsInterval: true, needsTime: false, needsDay: false },
    { value: 'hours', label: 'hours', needsInterval: true, needsTime: false, needsDay: false },
    { value: 'day', label: 'day', needsInterval: false, needsTime: true, needsDay: false },
    { value: 'week', label: 'week', needsInterval: false, needsTime: true, needsDay: 'week' },
    { value: 'weeks', label: 'weeks', needsInterval: true, needsTime: true, needsDay: 'week' },
    { value: 'month', label: 'month', needsInterval: false, needsTime: true, needsDay: 'month' },
] as const;

const DAYS_OF_WEEK = [
    { value: 0, label: 'Sunday' },
    { value: 1, label: 'Monday' },
    { value: 2, label: 'Tuesday' },
    { value: 3, label: 'Wednesday' },
    { value: 4, label: 'Thursday' },
    { value: 5, label: 'Friday' },
    { value: 6, label: 'Saturday' },
];

const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => ({
    value: i + 1,
    label: `${i + 1}${getOrdinalSuffix(i + 1)}`,
}));

function getOrdinalSuffix(n: number): string {
    if (n > 3 && n < 21) return 'th';
    switch (n % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
    }
}

// Generate time options (every 15 minutes)
const TIME_OPTIONS = Array.from({ length: 96 }, (_, i) => {
    const hour = Math.floor(i / 4);
    const minute = (i % 4) * 15;
    const hour12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
    const ampm = hour < 12 ? 'AM' : 'PM';
    const label = `${hour12}:${minute.toString().padStart(2, '0')} ${ampm}`;
    return { hour, minute, label, value: `${hour}:${minute}` };
});

// Window bound options: same 15-min grid, but valued as zero-padded 24h
// "HH:MM" — the wire format of windowStart/windowEnd.
const WINDOW_TIME_OPTIONS = TIME_OPTIONS.map(({ hour, minute, label }) => ({
    label,
    value: `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
}));

const MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
];
const MONTH_OPTIONS = MONTH_NAMES.map((label, i) => ({ value: i + 1, label }));

const DAY_CHIP_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

// ---------------------------------------------------------------------------
// Narrowing pills: the schedule is one always-complete sentence — "Every 30
// minutes · all day · every day · all year". Each dimension is a permanently
// visible inline word (muted while unconstrained) that opens a small popover;
// clearing is semantic ("All day", "Every day", "Any day"), never a delete
// row. Applicability mirrors the backend's _*_FREQUENCIES maps.
// ---------------------------------------------------------------------------
type ConstraintKey = 'timeOfDay' | 'weekDays' | 'monthDays' | 'months';

const CONSTRAINT_APPLICABILITY: Record<ConstraintKey, string[]> = {
    timeOfDay: ['seconds', 'minutes', 'hours'],
    weekDays: ['seconds', 'minutes', 'hours', 'day'],
    monthDays: ['seconds', 'minutes', 'hours', 'day'],
    months: ['seconds', 'minutes', 'hours', 'day', 'week', 'month'],
};

const CONSTRAINT_FIELDS: Record<ConstraintKey, (keyof ScheduleConfig)[]> = {
    timeOfDay: ['windowStart', 'windowEnd'],
    weekDays: ['daysOfWeek'],
    monthDays: ['monthDayStart', 'monthDayEnd'],
    months: ['monthStart', 'monthEnd'],
};

/** Fields cleared when the frequency stops supporting their constraint. */
function pruneConstraintsForFrequency(config: ScheduleConfig, freq: string): Partial<ScheduleConfig> {
    const patch: Partial<ScheduleConfig> = {};
    for (const key of Object.keys(CONSTRAINT_APPLICABILITY) as ConstraintKey[]) {
        if (!CONSTRAINT_APPLICABILITY[key].includes(freq)) {
            for (const f of CONSTRAINT_FIELDS[key]) (patch as Record<string, undefined>)[f] = undefined;
        }
    }
    return patch;
}

// ---------------------------------------------------------------------------
// Custom dropdown component matching app design
// ---------------------------------------------------------------------------
function Dropdown({
    value,
    onChange,
    options,
    placeholder = 'Select...',
}: {
    value: string | number;
    onChange: (value: string) => void;
    options: { value: string | number; label: string }[];
    placeholder?: string;
}) {
    const [isOpen, setIsOpen] = useState(false);
    const [highlightedIndex, setHighlightedIndex] = useState(0);
    const buttonRef = useRef<HTMLButtonElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const menuRef = useRef<HTMLDivElement>(null);
    const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);

    const selectedOption = options.find(o => String(o.value) === String(value));
    const selectedIndex = options.findIndex(o => String(o.value) === String(value));

    // Position the portal menu below the button
    const updatePosition = useCallback(() => {
        if (!buttonRef.current) return;
        const rect = buttonRef.current.getBoundingClientRect();
        setMenuPos({ top: rect.bottom + 4, left: rect.left });
    }, []);

    // Close on outside click
    useEffect(() => {
        if (!isOpen) return;
        const handleClickOutside = (e: MouseEvent) => {
            const target = e.target as Node;
            if (buttonRef.current?.contains(target)) return;
            if (menuRef.current?.contains(target)) return;
            setIsOpen(false);
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen]);

    // Update position on open and on scroll/resize
    useEffect(() => {
        if (!isOpen) return;
        updatePosition();
        window.addEventListener('scroll', updatePosition, true);
        window.addEventListener('resize', updatePosition);
        return () => {
            window.removeEventListener('scroll', updatePosition, true);
            window.removeEventListener('resize', updatePosition);
        };
    }, [isOpen, updatePosition]);

    // Reset highlight when opening
    useEffect(() => {
        if (isOpen) {
            setHighlightedIndex(selectedIndex >= 0 ? selectedIndex : 0);
        }
    }, [isOpen, selectedIndex]);

    // Scroll highlighted item into view
    useEffect(() => {
        if (isOpen && listRef.current) {
            const highlightedEl = listRef.current.querySelector(`[data-index="${highlightedIndex}"]`);
            highlightedEl?.scrollIntoView({ block: 'nearest' });
        }
    }, [highlightedIndex, isOpen]);

    // Keyboard navigation
    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (!isOpen) {
            if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setIsOpen(true);
            }
            return;
        }

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                setHighlightedIndex(prev => (prev < options.length - 1 ? prev + 1 : 0));
                break;
            case 'ArrowUp':
                e.preventDefault();
                setHighlightedIndex(prev => (prev > 0 ? prev - 1 : options.length - 1));
                break;
            case 'Enter':
            case 'Tab':
                e.preventDefault();
                onChange(String(options[highlightedIndex].value));
                setIsOpen(false);
                break;
            case 'Escape':
                e.preventDefault();
                setIsOpen(false);
                break;
        }
    };

    return (
        <div className="relative">
            <button
                ref={buttonRef}
                type="button"
                onClick={() => setIsOpen(!isOpen)}
                onKeyDown={handleKeyDown}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1.5
                    ${isOpen
                        ? 'bg-foreground/[0.1] text-foreground border border-foreground/[0.2]'
                        : 'bg-card dark:bg-foreground/[0.04] text-foreground border border-border dark:border-white/[0.08] hover:border-border dark:hover:border-white/[0.15] hover:bg-muted dark:hover:bg-foreground/[0.06]'
                    }`}
            >
                <span>{selectedOption?.label || placeholder}</span>
                <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`} />
            </button>

            {isOpen && menuPos && createPortal(
                <div
                    ref={menuRef}
                    className="fixed min-w-[140px] bg-card/95 backdrop-blur-sm
                        border border-border/50 dark:border-zinc-700/50 rounded-lg shadow-2xl z-[9999] overflow-hidden animate-in fade-in duration-100"
                    style={{ top: menuPos.top, left: menuPos.left }}
                >
                    <div ref={listRef} className="max-h-52 overflow-y-auto">
                        {options.map((opt, idx) => {
                            const isSelected = String(opt.value) === String(value);
                            const isHighlighted = idx === highlightedIndex;
                            return (
                                <button
                                    key={opt.value}
                                    type="button"
                                    data-index={idx}
                                    onClick={() => {
                                        onChange(String(opt.value));
                                        setIsOpen(false);
                                    }}
                                    onMouseEnter={() => setHighlightedIndex(idx)}
                                    className={`w-full px-3 py-2 text-sm text-left flex items-center justify-between transition-colors
                                        ${isHighlighted ? 'bg-foreground/[0.08]' : ''}
                                        ${isSelected ? 'text-foreground' : 'text-foreground/80'}`}
                                >
                                    <span>{opt.label}</span>
                                    {isSelected && (
                                        <div className="h-1.5 w-1.5 rounded-full bg-foreground/60" />
                                    )}
                                </button>
                            );
                        })}
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// ScheduleWidget
// ---------------------------------------------------------------------------
export function ScheduleWidget({ value, onChange, excludeFrequencies, showWindow }: ScheduleWidgetProps) {
    const config = value || { frequency: 'hours', interval: 1, hour: 9, minute: 0, dayOfWeek: 1, dayOfMonth: 1 };

    const availableFrequencies = excludeFrequencies
        ? FREQUENCY_OPTIONS.filter(f => !excludeFrequencies.includes(f.value))
        : FREQUENCY_OPTIONS;
    const frequencyMeta = availableFrequencies.find(f => f.value === config.frequency) || availableFrequencies[1] || FREQUENCY_OPTIONS[2];

    const handleFrequencyChange = (newFreq: string) => {
        const meta = FREQUENCY_OPTIONS.find(f => f.value === newFreq);
        onChange({
            ...config,
            frequency: newFreq,
            interval: meta?.needsInterval ? (config.interval || 5) : undefined,
            hour: meta?.needsTime ? (config.hour ?? 9) : undefined,
            minute: meta?.needsTime ? (config.minute ?? 0) : undefined,
            dayOfWeek: meta?.needsDay === 'week' ? (config.dayOfWeek ?? 1) : undefined,
            dayOfMonth: meta?.needsDay === 'month' ? (config.dayOfMonth ?? 1) : undefined,
            // Constraints the new frequency can't honor are cleared so the
            // backend validator never sees an impossible combo.
            ...pruneConstraintsForFrequency(config, newFreq),
        });
    };

    const handleTimeChange = (val: string) => {
        const [h, m] = val.split(':').map(Number);
        onChange({ ...config, hour: h, minute: m });
    };

    return (
        <div className="space-y-3">
            {/* Main row: Every [interval?] [frequency] [on day?] [at time?] */}
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm text-muted-foreground">Every</span>

                {/* Interval input (for seconds/minutes/hours/weeks) */}
                {frequencyMeta.needsInterval && (
                    <input
                        type="number"
                        min={1}
                        max={config.frequency === 'seconds' ? 59 : config.frequency === 'minutes' ? 59 : config.frequency === 'weeks' ? 52 : 23}
                        value={config.interval ?? 5}
                        onChange={(e) => onChange({ ...config, interval: Math.max(1, parseInt(e.target.value) || 1) })}
                        className="w-20 px-2 py-1.5 bg-card dark:bg-foreground/[0.04] border border-border dark:border-white/[0.08] rounded-lg
                            text-sm text-foreground text-center focus:outline-none focus:border-border dark:focus:border-white/[0.15]
                            hover:border-border dark:hover:border-white/[0.12] transition-colors [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    />
                )}

                {/* Frequency dropdown */}
                <Dropdown
                    value={config.frequency}
                    onChange={handleFrequencyChange}
                    options={availableFrequencies.map(f => ({ value: f.value, label: f.label }))}
                />

                {/* Day of week (for weekly) */}
                {frequencyMeta.needsDay === 'week' && (
                    <>
                        <span className="text-sm text-muted-foreground">on</span>
                        <Dropdown
                            value={config.dayOfWeek ?? 1}
                            onChange={(v) => onChange({ ...config, dayOfWeek: parseInt(v) })}
                            options={DAYS_OF_WEEK}
                        />
                    </>
                )}

                {/* Day of month (for monthly) */}
                {frequencyMeta.needsDay === 'month' && (
                    <>
                        <span className="text-sm text-muted-foreground">on the</span>
                        <Dropdown
                            value={config.dayOfMonth ?? 1}
                            onChange={(v) => onChange({ ...config, dayOfMonth: parseInt(v) })}
                            options={DAYS_OF_MONTH}
                        />
                    </>
                )}

                {/* Time (for day/week/month) */}
                {frequencyMeta.needsTime && (
                    <>
                        <span className="text-sm text-muted-foreground">at</span>
                        <Dropdown
                            value={`${config.hour ?? 9}:${config.minute ?? 0}`}
                            onChange={handleTimeChange}
                            options={TIME_OPTIONS}
                        />
                    </>
                )}

                {/* Narrowing pills continue the sentence (adaptive to frequency) */}
                {showWindow && <SentencePills config={config} onChange={onChange} />}
            </div>

            {/* Human-readable summary */}
            <p className="text-xs text-muted-foreground dark:text-zinc-500">
                {getScheduleSummary(config)}
            </p>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Sentence pills + popovers
// ---------------------------------------------------------------------------

/** Small portal card anchored below a trigger; closes on outside click/Escape. */
function Popover({
    anchorRef,
    onClose,
    children,
}: {
    anchorRef: RefObject<HTMLButtonElement | null>;
    onClose: () => void;
    children: ReactNode;
}) {
    const cardRef = useRef<HTMLDivElement>(null);
    const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

    const updatePosition = useCallback(() => {
        const rect = anchorRef.current?.getBoundingClientRect();
        if (rect) setPos({ top: rect.bottom + 6, left: rect.left });
    }, [anchorRef]);

    useEffect(() => {
        updatePosition();
        window.addEventListener('scroll', updatePosition, true);
        window.addEventListener('resize', updatePosition);
        return () => {
            window.removeEventListener('scroll', updatePosition, true);
            window.removeEventListener('resize', updatePosition);
        };
    }, [updatePosition]);

    useEffect(() => {
        const onDown = (e: MouseEvent) => {
            const target = e.target as Node;
            if (anchorRef.current?.contains(target)) return;
            if (cardRef.current?.contains(target)) return;
            onClose();
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [anchorRef, onClose]);

    if (!pos) return null;
    return createPortal(
        <div
            ref={cardRef}
            className="fixed bg-card/95 backdrop-blur-sm border border-border/50 dark:border-zinc-700/50
                rounded-lg shadow-2xl z-[9999] p-3 animate-in fade-in duration-100"
            style={{ top: pos.top, left: pos.left }}
        >
            {children}
        </div>,
        document.body,
    );
}

/** An inline sentence word that edits one constraint dimension. */
function Pill({
    label,
    constrained,
    open,
    onClick,
    buttonRef,
}: {
    label: string;
    constrained: boolean;
    open: boolean;
    onClick: () => void;
    buttonRef: RefObject<HTMLButtonElement | null>;
}) {
    return (
        <button
            ref={buttonRef}
            type="button"
            onClick={onClick}
            className={`text-sm border-b border-dashed transition-colors
                ${open
                    ? 'text-foreground border-foreground/60'
                    : constrained
                        ? 'text-foreground border-foreground/40 hover:border-foreground/70'
                        : 'text-muted-foreground/70 border-muted-foreground/30 hover:text-foreground hover:border-foreground/50'
                }`}
        >
            {label}
        </button>
    );
}

const SELECT_CLS = `bg-card dark:bg-foreground/[0.04] border border-border dark:border-white/[0.08]
    rounded-md px-2 py-1 text-sm text-foreground focus:outline-none focus:border-foreground/[0.25]`;
const POPOVER_MUTED = 'text-sm text-muted-foreground';
const PRESET_CLS = 'px-2 py-1 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors';

function TimePopover({
    config,
    set,
    onClear,
}: {
    config: ScheduleConfig;
    set: (patch: Partial<ScheduleConfig>) => void;
    onClear: () => void;
}) {
    // Opening the pill already committed a window (see SentencePills), so the
    // selects always show the REAL stored values — never uncommitted
    // suggestions that look set while the schedule still runs all day.
    // padStart: AI-builder writes may carry "9:00", but option values are
    // zero-padded "09:00".
    const start = String(config.windowStart ?? '09:00').padStart(5, '0');
    const end = String(config.windowEnd ?? '18:00').padStart(5, '0');
    return (
        <div className="flex items-center gap-2">
            <span className={POPOVER_MUTED}>from</span>
            <select
                className={SELECT_CLS}
                value={start}
                onChange={(e) => set({ windowStart: e.target.value, windowEnd: end })}
            >
                {WINDOW_TIME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                ))}
            </select>
            <span className={POPOVER_MUTED}>to</span>
            <select
                className={SELECT_CLS}
                value={end}
                onChange={(e) => set({ windowStart: start, windowEnd: e.target.value })}
            >
                {WINDOW_TIME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                ))}
            </select>
            <button type="button" className={PRESET_CLS} onClick={onClear}>
                All day
            </button>
        </div>
    );
}

function DaysPopover({
    config,
    set,
}: {
    config: ScheduleConfig;
    set: (patch: Partial<ScheduleConfig>) => void;
}) {
    // Coerce before comparing: entries may be strings ("1" — AI-builder XML
    // writes), and mixed types once stranded a duplicate + made selected
    // chips unhighlightable/unremovable. Toggling writes clean numbers back.
    const days = [...new Set((config.daysOfWeek ?? []).map(Number))].filter(
        (d) => d >= 0 && d <= 6,
    );
    const toggleDay = (day: number) => {
        const current = new Set(days);
        if (current.has(day)) current.delete(day);
        else current.add(day);
        set({ daysOfWeek: [...current].sort((a, b) => a - b) });
    };
    return (
        <div className="space-y-2">
            <div className="flex items-center gap-1">
                {DAY_CHIP_LABELS.map((label, day) => {
                    const active = days.includes(day);
                    return (
                        <button
                            key={day}
                            type="button"
                            onClick={() => toggleDay(day)}
                            title={DAYS_OF_WEEK[day].label}
                            className={`w-7 h-7 rounded-full text-xs font-medium transition-colors border
                                ${active
                                    ? 'bg-primary text-primary-foreground border-transparent'
                                    : 'bg-card dark:bg-foreground/[0.04] text-muted-foreground border-border dark:border-white/[0.08] hover:text-foreground hover:border-foreground/[0.2]'
                                }`}
                        >
                            {label}
                        </button>
                    );
                })}
            </div>
            <div className="flex items-center gap-1">
                <button type="button" className={PRESET_CLS} onClick={() => set({ daysOfWeek: undefined })}>
                    Every day
                </button>
                <button type="button" className={PRESET_CLS} onClick={() => set({ daysOfWeek: [1, 2, 3, 4, 5] })}>
                    Weekdays
                </button>
                <button type="button" className={PRESET_CLS} onClick={() => set({ daysOfWeek: [0, 6] })}>
                    Weekends
                </button>
            </div>
        </div>
    );
}

function CalendarPopover({
    config,
    set,
    allowMonthDays,
    allowMonths,
}: {
    config: ScheduleConfig;
    set: (patch: Partial<ScheduleConfig>) => void;
    allowMonthDays: boolean;
    allowMonths: boolean;
}) {
    const both = allowMonthDays && allowMonths;
    const header = (text: string) =>
        both ? (
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-1">{text}</div>
        ) : null;
    return (
        <div className="space-y-3">
            {allowMonthDays && (
                <div>
                    {header('Days of the month')}
                    <div className="flex items-center gap-2">
                        <select
                            className={SELECT_CLS}
                            value={config.monthDayStart ?? 0}
                            onChange={(e) => {
                                const v = parseInt(e.target.value);
                                if (v === 0) set({ monthDayStart: undefined, monthDayEnd: undefined });
                                else set({ monthDayStart: v, monthDayEnd: config.monthDayEnd ?? v });
                            }}
                        >
                            <option value={0}>Any day</option>
                            {DAYS_OF_MONTH.map((o) => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                        {config.monthDayStart != null && (
                            <>
                                <span className={POPOVER_MUTED}>to</span>
                                <select
                                    className={SELECT_CLS}
                                    value={config.monthDayEnd ?? config.monthDayStart}
                                    onChange={(e) => set({ monthDayEnd: parseInt(e.target.value) })}
                                >
                                    {DAYS_OF_MONTH.map((o) => (
                                        <option key={o.value} value={o.value}>{o.label}</option>
                                    ))}
                                </select>
                            </>
                        )}
                    </div>
                </div>
            )}
            {allowMonths && (
                <div>
                    {header('Months')}
                    <div className="flex items-center gap-2">
                        <select
                            className={SELECT_CLS}
                            value={config.monthStart ?? 0}
                            onChange={(e) => {
                                const v = parseInt(e.target.value);
                                if (v === 0) set({ monthStart: undefined, monthEnd: undefined });
                                else set({ monthStart: v, monthEnd: config.monthEnd ?? v });
                            }}
                        >
                            <option value={0}>All year</option>
                            {MONTH_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                        {config.monthStart != null && (
                            <>
                                <span className={POPOVER_MUTED}>through</span>
                                <select
                                    className={SELECT_CLS}
                                    value={config.monthEnd ?? config.monthStart}
                                    onChange={(e) => set({ monthEnd: parseInt(e.target.value) })}
                                >
                                    {MONTH_OPTIONS.map((o) => (
                                        <option key={o.value} value={o.value}>{o.label}</option>
                                    ))}
                                </select>
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

/** The sentence's narrowing pills — rendered inline in the main cadence row. */
function SentencePills({
    config,
    onChange,
}: {
    config: ScheduleConfig;
    onChange: (value: ScheduleConfig) => void;
}) {
    const [openPill, setOpenPill] = useState<'time' | 'days' | 'dates' | null>(null);
    const timeRef = useRef<HTMLButtonElement>(null);
    const daysRef = useRef<HTMLButtonElement>(null);
    const datesRef = useRef<HTMLButtonElement>(null);
    const set = (patch: Partial<ScheduleConfig>) => onChange({ ...config, ...patch });

    const freq = config.frequency;
    const showTime = CONSTRAINT_APPLICABILITY.timeOfDay.includes(freq);
    const showDays = CONSTRAINT_APPLICABILITY.weekDays.includes(freq);
    const allowMonthDays = CONSTRAINT_APPLICABILITY.monthDays.includes(freq);
    const allowMonths = CONSTRAINT_APPLICABILITY.months.includes(freq);
    const showDates = allowMonthDays || allowMonths;
    if (!showTime && !showDays && !showDates) return null;

    const timeLbl = windowLabel(config);
    const daysLbl = daysLabel(config.daysOfWeek);
    const datesLbl = calendarLabel(config);
    const toggle = (pill: 'time' | 'days' | 'dates') =>
        setOpenPill(openPill === pill ? null : pill);

    const sep = <span className="text-sm text-muted-foreground/40 select-none">·</span>;

    return (
        <>
            {showTime && (
                <>
                    {sep}
                    <Pill
                        buttonRef={timeRef}
                        label={timeLbl || 'all day'}
                        constrained={!!timeLbl}
                        open={openPill === 'time'}
                        onClick={() => {
                            // Opening COMMITS the starting window so the pill
                            // and popover always show what is actually set —
                            // a prefilled-but-unsaved 9–6 looked already
                            // applied while the schedule still ran all day.
                            if (config.windowStart == null && openPill !== 'time') {
                                set({ windowStart: '09:00', windowEnd: '18:00' });
                            }
                            toggle('time');
                        }}
                    />
                </>
            )}
            {showDays && (
                <>
                    {sep}
                    <Pill
                        buttonRef={daysRef}
                        label={daysLbl || 'every day'}
                        constrained={!!daysLbl}
                        open={openPill === 'days'}
                        onClick={() => toggle('days')}
                    />
                </>
            )}
            {showDates && (
                <>
                    {sep}
                    <Pill
                        buttonRef={datesRef}
                        label={datesLbl || 'all year'}
                        constrained={!!datesLbl}
                        open={openPill === 'dates'}
                        onClick={() => toggle('dates')}
                    />
                </>
            )}

            {openPill === 'time' && (
                <Popover anchorRef={timeRef} onClose={() => setOpenPill(null)}>
                    <TimePopover
                        config={config}
                        set={set}
                        onClear={() => {
                            set({ windowStart: undefined, windowEnd: undefined });
                            setOpenPill(null);
                        }}
                    />
                </Popover>
            )}
            {openPill === 'days' && (
                <Popover anchorRef={daysRef} onClose={() => setOpenPill(null)}>
                    <DaysPopover config={config} set={set} />
                </Popover>
            )}
            {openPill === 'dates' && (
                <Popover anchorRef={datesRef} onClose={() => setOpenPill(null)}>
                    <CalendarPopover
                        config={config}
                        set={set}
                        allowMonthDays={allowMonthDays}
                        allowMonths={allowMonths}
                    />
                </Popover>
            )}
        </>
    );
}

function getScheduleSummary(config: ScheduleConfig): string {
    const phrase = describeSchedule(config);
    return phrase ? `Runs ${phrase}` : '';
}

export default ScheduleWidget;
