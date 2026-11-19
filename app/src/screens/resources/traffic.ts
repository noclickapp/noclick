// An app's traffic in the words its page shows: requests, never visitors (the
// record counts every page, file and API call, people's and bots' alike), the
// change against the period before, and response times.
import { compactNumber } from '@/ui/primitives';
import type { AnalyticsPeriod, ProjectAnalytics } from 'noclick';

export const PERIODS: readonly { value: AnalyticsPeriod; label: string; words: string }[] = [
    { value: '24h', label: 'Last 24 hours', words: '24 hours' },
    { value: '7d', label: 'Last 7 days', words: '7 days' },
    { value: '30d', label: 'Last 30 days', words: '30 days' },
];

export function periodWords(period: AnalyticsPeriod): string {
    return PERIODS.find((p) => p.value === period)?.words ?? period;
}

/** The viewer's own time zone, which the hours and days start in. */
export function browserZone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
        return 'UTC';
    }
}

export function requestsLabel(n: number): string {
    return `${compactNumber(n)} ${n === 1 ? 'request' : 'requests'}`;
}

/** `42 ms`, `1.2 s`. */
export function formatMs(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

/** A share of requests: `0.25%`, `12%`, under a hundredth of a percent as `<0.01%`. */
export function formatShare(rate: number): string {
    if (rate === 0) return '0%';
    if (rate < 0.0001) return '<0.01%';
    const pct = rate * 100;
    return `${pct < 10 ? Number(pct.toFixed(2)) : Math.round(pct)}%`;
}

export interface Change {
    direction: 'up' | 'down' | 'flat';
    words: string;
}

/** This period against the same length of time before it; null when neither had a request. */
export function changeFrom(current: number, previous: number, period: AnalyticsPeriod): Change | null {
    const before = `the ${periodWords(period)} before`;
    if (!previous) return current ? { direction: 'up', words: `None ${before}` } : null;
    const pct = Math.round(((current - previous) / previous) * 100);
    if (pct === 0) return { direction: 'flat', words: `Same as ${before}` };
    return { direction: pct > 0 ? 'up' : 'down', words: `${Math.abs(pct).toLocaleString('en-US')}% ${pct > 0 ? 'more' : 'fewer'} than ${before}` };
}


/** An interval's start as its axis says it: `Oct 12` for a day, `14:00` for an hour, where the viewer is. */
export function intervalLabel(at: Date, interval: ProjectAnalytics['interval'], tz: string, long = false): string {
    const options: Intl.DateTimeFormatOptions =
        interval === 'hour'
            ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', ...(long ? { weekday: 'short' } : {}), timeZone: tz }
            : { month: 'short', day: 'numeric', ...(long ? { weekday: 'short' } : {}), timeZone: tz };
    return new Intl.DateTimeFormat('en-US', options).format(at);
}
