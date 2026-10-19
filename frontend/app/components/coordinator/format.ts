// How the coordinator's cards say when something happened or will: the time alone today ("9:41 AM"), the day for
// tomorrow and yesterday, the date otherwise, always in the reader's own timezone.

const DAY = 86_400_000;

function dayIndex(date: Date): number {
    return Math.floor((date.getTime() - date.getTimezoneOffset() * 60_000) / DAY);
}

export function clockTime(at: Date | number | string): string {
    return new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/** "today at 9:41 AM", "tomorrow at 2:00 PM", "Oct 6 at 9:00 AM". */
export function whenAt(at: Date | number | string, now: Date = new Date()): string {
    const date = new Date(at);
    const days = dayIndex(date) - dayIndex(now);
    const day =
        days === 0
            ? 'today'
            : days === 1
              ? 'tomorrow'
              : days === -1
                ? 'yesterday'
                : shortDate(date, now);
    return `${day} at ${clockTime(date)}`;
}

/** "2:14" for seconds. */
export function duration(seconds: number): string {
    const s = Math.max(0, Math.round(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

function shortDate(date: Date, now: Date): string {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric', ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) });
}

/** "9:41 AM" today, "Yesterday", then "Oct 5". */
export function shortWhen(at: Date | number | string, now: Date = new Date()): string {
    const date = new Date(at);
    const days = dayIndex(now) - dayIndex(date);
    return days === 0 ? clockTime(date) : days === 1 ? 'Yesterday' : shortDate(date, now);
}

/** "today at 9:41 AM" within a day, "Sep 28 – Oct 5" across days. */
export function dayRange(from: Date | number | string, to: Date | number | string, now: Date = new Date()): string {
    const [a, b] = [new Date(from), new Date(to)];
    return dayIndex(a) === dayIndex(b) ? whenAt(b, now) : `${shortDate(a, now)} – ${shortDate(b, now)}`;
}
