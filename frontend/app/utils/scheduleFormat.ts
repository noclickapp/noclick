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
    /** Days of week to run on (0=Sunday … 6=Saturday); empty = every day. */
    daysOfWeek?: (number | string)[];
    /** Part-of-day window, 24h "HH:MM" strings, both-inclusive. */
    windowStart?: string;
    windowEnd?: string;
    /** Part-of-month range (1-31) and part-of-year range (1-12), inclusive;
     * start > end wraps. */
    monthDayStart?: Numish;
    monthDayEnd?: Numish;
    monthStart?: Numish;
    monthEnd?: Numish;
    [key: string]: unknown;
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

/** "09:00" → "9:00 AM"; returns '' for anything unparseable (e.g. a {{ref}}). */
function formatWindowTime(value: string | undefined): string {
    const m = /^(\d{1,2}):(\d{2})$/.exec((value ?? '').trim());
    if (!m) return '';
    return formatTime12(Number(m[1]), Number(m[2]));
}

const DAY_ABBREV = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
];

// ── Constraint labels ───────────────────────────────────────────────────────
// Bare labels (no prepositions) shared by the widget's sentence pills and the
// prose composed in describeSchedule, so the two can never phrase differently.

/** "weekdays", "weekends", "Mon, Wed, Fri" — '' when every day. */
export function daysLabel(days: ScheduleEntry['daysOfWeek']): string {
    const values = [...new Set((days ?? []).map(toNum).filter(d => d >= 0 && d <= 6))].sort();
    if (values.length === 0 || values.length === 7) return '';
    if (values.join(',') === '1,2,3,4,5') return 'weekdays';
    if (values.join(',') === '0,6') return 'weekends';
    return values.map(d => DAY_ABBREV[d]).join(', ');
}

/** "on weekdays", "on Mon, Wed, Fri" — '' when every day. */
export function describeDays(days: ScheduleEntry['daysOfWeek']): string {
    const label = daysLabel(days);
    return label ? `on ${label}` : '';
}

/** "9:00 AM – 6:00 PM" — '' when unset/unparseable (e.g. a {{ref}}). */
export function windowLabel(s: ScheduleEntry): string {
    const start = formatWindowTime(s.windowStart);
    const end = formatWindowTime(s.windowEnd);
    return start && end ? `${start} – ${end}` : '';
}

const ord = (n: number) => `${n}${ordinalSuffix(n)}`;

function monthDayRange(s: ScheduleEntry): [number, number] | null {
    const a = toNum(s.monthDayStart), b = toNum(s.monthDayEnd);
    if (isNaN(a) || isNaN(b) || a < 1 || b < 1 || a > 31 || b > 31) return null;
    if (a === 1 && b === 31) return null; // full month = no constraint
    return [a, b];
}

function monthRange(s: ScheduleEntry): [number, number] | null {
    const a = toNum(s.monthStart), b = toNum(s.monthEnd);
    if (isNaN(a) || isNaN(b) || a < 1 || b < 1 || a > 12 || b > 12) return null;
    if (a === 1 && b === 12) return null; // whole year = no constraint
    return [a, b];
}

/**
 * Calendar (part-of-month + part-of-year) pill label, points collapsing to
 * the natural form: "August", "March – October", "10th of each month",
 * "10th – 15th of August", "10th – 15th, March – October". '' when unset.
 */
export function calendarLabel(s: ScheduleEntry): string {
    const md = monthDayRange(s);
    const mo = monthRange(s);
    const days = md ? (md[0] === md[1] ? ord(md[0]) : `${ord(md[0])} – ${ord(md[1])}`) : '';
    if (!mo) return md ? `${days} of each month` : '';
    const months = mo[0] === mo[1] ? MONTH_NAMES[mo[0] - 1] : `${MONTH_NAMES[mo[0] - 1]} – ${MONTH_NAMES[mo[1] - 1]}`;
    if (!md) return months;
    return mo[0] === mo[1] ? `${days} of ${months}` : `${days}, ${months}`;
}

/** Prose form of the calendar constraint (leading ", "): ", in August",
 * ", the 10th–15th of each month, March to October", ", on the 10th of August". */
function describeCalendar(s: ScheduleEntry): string {
    const md = monthDayRange(s);
    const mo = monthRange(s);
    if (!md && !mo) return '';
    const days = md ? (md[0] === md[1] ? `on the ${ord(md[0])}` : `the ${ord(md[0])}–${ord(md[1])}`) : '';
    if (!mo) return `, ${days} of each month`;
    const months = mo[0] === mo[1]
        ? MONTH_NAMES[mo[0] - 1]
        : `${MONTH_NAMES[mo[0] - 1]} to ${MONTH_NAMES[mo[1] - 1]}`;
    if (!md) return mo[0] === mo[1] ? `, in ${months}` : `, ${months}`;
    return mo[0] === mo[1] ? `, ${days} of ${months}` : `, ${days} of each month, ${months}`;
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

    // Interval schedules may be narrowed by stacked constraints.
    const windowStart = formatWindowTime(s.windowStart);
    const windowEnd = formatWindowTime(s.windowEnd);
    const windowStr = windowStart && windowEnd ? ` from ${windowStart} to ${windowEnd}` : '';
    const daysStr = describeDays(s.daysOfWeek);
    const calendarStr = describeCalendar(s);
    const suffix = `${windowStr}${daysStr ? ` ${daysStr}` : ''}${calendarStr}`;
    const daySuffix = `${daysStr ? ` ${daysStr}` : ''}${calendarStr}`;
    // week/month cadences take only the part-of-year constraint.
    const monthsOnlyStr = describeCalendar({ monthStart: s.monthStart, monthEnd: s.monthEnd });

    switch (s.frequency) {
        case 'seconds': return `every ${interval || 5} seconds${suffix}`;
        case 'minutes': return `every ${interval || 5} minutes${suffix}`;
        case 'hours': return `every ${interval} hour${interval > 1 ? 's' : ''}${suffix}`;
        case 'day': return `daily at ${timeStr}${daySuffix}`;
        case 'week': return `every ${DAY_NAMES[dayOfWeek] || 'Monday'} at ${timeStr}${monthsOnlyStr}`;
        case 'weeks': return `every ${interval || 2} weeks on ${DAY_NAMES[dayOfWeek] || 'Monday'} at ${timeStr}`;
        case 'month': {
            const d = dayOfMonth || 1;
            return `on the ${d}${ordinalSuffix(d)} of each month at ${timeStr}${monthsOnlyStr}`;
        }
        default: return '';
    }
}

/** Whether a schedule's wall-clock/calendar position is meaningful (so its
 * timezone matters) — any narrowing constraint makes it so. */
export function isTimeOfDaySchedule(s: ScheduleEntry): boolean {
    if (s.windowStart || s.windowEnd || (s.daysOfWeek?.length ?? 0) > 0) return true;
    if (s.monthDayStart != null || s.monthStart != null) return true;
    return s.frequency === 'day' || s.frequency === 'week' || s.frequency === 'weeks' || s.frequency === 'month';
}

/** The concrete schedule objects in a cron config, skipping unresolved {{ref}} strings. */
export function getScheduleEntries(config: Record<string, unknown> | undefined): ScheduleEntry[] {
    const raw = config?.schedules;
    if (!Array.isArray(raw)) return [];
    return raw.filter((s): s is ScheduleEntry => !!s && typeof s === 'object' && !Array.isArray(s));
}
