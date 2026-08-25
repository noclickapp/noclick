/**
 * ScheduleWidget - An intuitive schedule picker for cron triggers.
 * Adapts its UI based on the selected frequency to show only relevant options.
 * Pure controlled component — no drag-and-drop (D&D happens at the whole-schedule
 * level in SchedulesWidget instead).
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';
import { describeSchedule } from '~/utils/scheduleFormat';

export interface ScheduleConfig {
    frequency: string;
    interval?: number;
    hour?: number;
    minute?: number;
    dayOfWeek?: number;
    dayOfMonth?: number;
}

interface ScheduleWidgetProps {
    value: ScheduleConfig;
    onChange: (value: ScheduleConfig) => void;
    /** Frequency values to exclude from the dropdown (e.g., ['seconds']) */
    excludeFrequencies?: string[];
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
export function ScheduleWidget({ value, onChange, excludeFrequencies }: ScheduleWidgetProps) {
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
            </div>

            {/* Human-readable summary */}
            <p className="text-xs text-muted-foreground dark:text-zinc-500">
                {getScheduleSummary(config)}
            </p>
        </div>
    );
}

function getScheduleSummary(config: ScheduleConfig): string {
    const phrase = describeSchedule(config);
    return phrase ? `Runs ${phrase}` : '';
}

export default ScheduleWidget;
