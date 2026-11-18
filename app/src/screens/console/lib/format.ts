// Console formatters: money, ids, durations and the three time tiers
// (relative in lists, absolute to seconds in run tables, milliseconds in logs).
import { compactNumber, fmtDuration, relTime } from '@/lib/formatters';

export { compactNumber as formatCount };

const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const USD_FULL = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 });

/** Tables and tiles: two decimals, `<$0.01` for a non-zero sub-cent amount, "Unknown" for null. */
export function formatMoney(usd: number | null | undefined): string {
    if (usd == null || Number.isNaN(usd)) return 'Unknown';
    if (usd !== 0 && Math.abs(usd) < 0.005) return usd < 0 ? '-<$0.01' : '<$0.01';
    return USD.format(usd);
}

/** Tooltips and drawers: full precision (`$0.0042`). */
export function formatMoneyFull(usd: number | null | undefined): string {
    if (usd == null || Number.isNaN(usd)) return 'Unknown';
    return USD_FULL.format(usd);
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** NoClick's own ids (an agent's, an operation's) are UUIDs; a user's id is yours and can be anything. */
export function isUuid(value: string): boolean {
    return UUID_RE.test(value);
}

/** `3f2a…9c1e`; short values pass through. */
export function truncateId(id: string, head = 4, tail = 4): string {
    return id.length <= head + tail + 1 ? id : `${id.slice(0, head)}…${id.slice(-tail)}`;
}

/** `0ms`, `120ms`, `2.72s`, `1m 30s`. */
export function formatDuration(ms: number | null | undefined): string {
    if (ms == null || Number.isNaN(ms)) return '';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(2).replace(/\.?0+$/, '')}s`;
    return fmtDuration(ms);
}

type TimeInput = string | Date | number;

function toDate(value: TimeInput): Date {
    return value instanceof Date ? value : new Date(value);
}

/** Lists: "3m ago", "yesterday", "Aug 24". */
export function formatRelative(value: TimeInput, now: number): string {
    return relTime(toDate(value).toISOString(), new Date(now).toISOString());
}

const absoluteFormats = new Map<string, Intl.DateTimeFormat>();

function absoluteFormat(timeZone: string | undefined): Intl.DateTimeFormat {
    const cacheKey = timeZone ?? '';
    let fmt = absoluteFormats.get(cacheKey);
    if (!fmt) {
        fmt = new Intl.DateTimeFormat('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hourCycle: 'h23',
            timeZone,
        });
        absoluteFormats.set(cacheKey, fmt);
    }
    return fmt;
}

/** Run tables: `Sep 26, 2026, 16:20:05` (local time unless a zone is given). */
export function formatAbsolute(value: TimeInput, timeZone?: string): string {
    return absoluteFormat(timeZone).format(toDate(value));
}

/** Logs: `16:20:05.972`. */
export function formatLogTime(value: TimeInput, timeZone?: string): string {
    const d = toDate(value);
    const parts = absoluteFormat(timeZone).formatToParts(d);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    return `${get('hour')}:${get('minute')}:${get('second')}.${String(d.getMilliseconds()).padStart(3, '0')}`;
}

/** The hover text for any time: UTC and local, absolute. */
export function formatTimeTooltip(value: TimeInput): string {
    return `${formatAbsolute(value, 'UTC')} UTC · ${formatAbsolute(value)} local`;
}

/** `42%`, one decimal below 10%. */
export function formatPercent(ratio: number): string {
    const pct = ratio * 100;
    return `${pct < 10 && pct > 0 ? pct.toFixed(1) : Math.round(pct)}%`;
}
