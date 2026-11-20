// Times, sizes, counts and dollars as the app prints them. Plain functions, apart from ui/primitives.tsx (which draws
// the node marks) so a page that only formats a number doesn't load those.

const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad2 = (n: number) => String(n).padStart(2, '0');

/** "3m ago" · "2h ago" · "yesterday" · "Aug 24". Relative to `now`, so server and browser print the same. */
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

/** "just now" · "5m ago" · "2d ago" · "3mo ago", against the clock: where space is tight (an automation's card or row,
 *  a "+" list). '' for no time, so a caller can `&&` it. */
export function relativeShort(iso?: string): string {
    if (!iso) return '';
    const ts = new Date(iso).getTime();
    if (!Number.isFinite(ts)) return '';
    const sec = (Date.now() - ts) / 1000;
    if (sec < 60) return 'just now';
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 86400 * 30) return `${Math.floor(sec / 86400)}d ago`;
    if (sec < 86400 * 365) return `${Math.floor(sec / (86400 * 30))}mo ago`;
    return `${Math.floor(sec / (86400 * 365))}y ago`;
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

/** A file's size as its card prints it: "512 B", "3.4 KB", "1.2 MB"; nothing for none. */
export function formatSize(bytes?: number): string {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

/** A price already in dollars (a vendor's, like a domain's): 12.99 → "$12.99". */
export function formatDollars(usd: number): string {
    return USD.format(usd);
}

/** A metered amount in dollars, precise enough that a small real charge never rounds away: a 30s sandbox beat is
 *  "$0.0063", a short model call "<$0.0001". */
export function usageDollars(usd: number): string {
    if (usd === 0) return '$0';
    if (usd >= 0.1) return USD.format(usd);
    if (usd >= 0.0001) return `$${Number(usd.toPrecision(2))}`;
    return '<$0.0001';
}

/** When an account was added, where nothing else tells it apart: "Added Nov 19, 2026". */
export function addedLabel(iso: string): string {
    return `Added ${new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

const WHOLE_USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

/** An amount of funds: whole dollars as "$5", any other with its cents, "$5.50". */
export function formatFunds(usd: number): string {
    return Number.isInteger(usd) ? WHOLE_USD.format(usd) : USD.format(usd);
}
