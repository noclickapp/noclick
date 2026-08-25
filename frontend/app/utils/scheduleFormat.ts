// Human-readable formatting for cron schedule entries (the ScheduleConfig objects
// stored in a trigger-cron node's `config.schedules`). Extracted so the config
// widget's summary line and the Run trigger-info popup describe a schedule the
// same way instead of each rolling its own formatter.

type Numish = number | string | null | undefined;

export interface ScheduleEntry {
    frequency?: string;
    interval?: Numish;
    hour?: Numish;
    minute?: Numish;
    dayOfWeek?: Numish;
    dayOfMonth?: Numish;
}

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

export function ordinalSuffix(n: number): string {
    if (n > 3 && n < 21) return 'th';
    switch (n % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
    }
}

function formatTime12(hour: number, minute: number): string {
    const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
    return `${h12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`;
}

// Coerce a field that may arrive as a number, a numeric string, or a {{ref}}.
function toNum(v: Numish): number {
    return typeof v === 'number' ? v : Number(v);
}

/**
 * Describe one schedule entry as a lowercase phrase, e.g. "daily at 9:00 AM",
 * "every Monday at 8:00 AM", "every 5 minutes". Callers prepend "Runs " (widget)
 * or capitalize it (popup). Returns '' for an unrecognized/empty frequency.
 */
export function describeSchedule(s: ScheduleEntry): string {
    const interval = toNum(s.interval) || 1;
    const h = toNum(s.hour);
    const m = toNum(s.minute);
    const dayOfWeek = toNum(s.dayOfWeek);
    const dayOfMonth = toNum(s.dayOfMonth);
    const timeStr = !isNaN(h) && !isNaN(m) ? formatTime12(h, m) : '';

    switch (s.frequency) {
        case 'seconds': return `every ${interval || 5} seconds`;
        case 'minutes': return `every ${interval || 5} minutes`;
        case 'hours': return `every ${interval} hour${interval > 1 ? 's' : ''}`;
        case 'day': return `daily at ${timeStr}`;
        case 'week': return `every ${DAY_NAMES[dayOfWeek] || 'Monday'} at ${timeStr}`;
        case 'weeks': return `every ${interval || 2} weeks on ${DAY_NAMES[dayOfWeek] || 'Monday'} at ${timeStr}`;
        case 'month': {
            const d = dayOfMonth || 1;
            return `on the ${d}${ordinalSuffix(d)} of each month at ${timeStr}`;
        }
        default: return '';
    }
}

/** Whether a schedule's time-of-day is meaningful (so its timezone matters). */
export function isTimeOfDaySchedule(s: ScheduleEntry): boolean {
    return s.frequency === 'day' || s.frequency === 'week' || s.frequency === 'weeks' || s.frequency === 'month';
}

/** The concrete schedule objects in a cron config, skipping unresolved {{ref}} strings. */
export function getScheduleEntries(config: Record<string, unknown> | undefined): ScheduleEntry[] {
    const raw = config?.schedules;
    if (!Array.isArray(raw)) return [];
    return raw.filter((s): s is ScheduleEntry => !!s && typeof s === 'object' && !Array.isArray(s));
}
