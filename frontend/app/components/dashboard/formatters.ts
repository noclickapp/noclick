// Times, sizes and counts as the dashboard's surfaces print them. Plain functions, apart from primitives.tsx (which
// draws marks from every node schema) so a page that only formats a number doesn't load the schemas.

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad2 = (n: number) => String(n).padStart(2, '0');

/** "3m ago" · "2h ago" · "yesterday" · "Aug 24". Relative to the fixture clock. */
export function relTime(iso: string, now: string): string {
    const t = Date.parse(iso);
    const n = Date.parse(now);
    if (Number.isNaN(t) || Number.isNaN(n)) return '';
    const diff = n - t;
    const future = diff < 0;
    const abs = Math.abs(diff);
    const m = Math.round(abs / 60_000);
    if (m < 1) return 'now';
    if (m < 60) return future ? `in ${m}m` : `${m}m ago`;
    const hrs = Math.round(m / 60);
    if (hrs < 24) return future ? `in ${hrs}h` : `${hrs}h ago`;
    const dd = Math.round(hrs / 24);
    if (dd === 1) return future ? 'tomorrow' : 'yesterday';
    if (dd < 7) return future ? `in ${dd}d` : `${dd}d ago`;
    const dt = new Date(t);
    return `${MONTHS[dt.getMonth()]} ${dt.getDate()}`;
}

export function clockLabel(iso: string): string {
    const dt = new Date(iso);
    return `${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

export function dateLabel(iso: string): string {
    const dt = new Date(iso);
    return `${MONTHS[dt.getMonth()]} ${dt.getDate()}, ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

export function fmtBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function fmtDuration(ms: number | null): string {
    if (ms == null) return '';
    if (ms < 1000) return `${ms}ms`;
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rest = s % 60;
    if (m < 60) return rest ? `${m}m ${rest}s` : `${m}m`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function compactNumber(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 10_000) return `${(n / 1000).toFixed(1)}K`;
    return n.toLocaleString('en-US');
}

/** "1 row", "312 rows", "12.4K rows": a count with its noun (one and many, or one that takes an s). */
export function countOf(n: number, noun: string | readonly [string, string]): string {
    const [one, many] = typeof noun === 'string' ? [noun, `${noun}s`] : noun;
    return `${compactNumber(n)} ${n === 1 ? one : many}`;
}
