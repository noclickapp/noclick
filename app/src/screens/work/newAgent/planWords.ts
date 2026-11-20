// How a plan's usage reads in Work's account pill and its menu: when a window resets ("in 1 h 40 min" later today,
// "tomorrow 9:00 AM", "Thu 9:00 AM" after), how much of a window is used ("62% used", "Used up"), and what the pill adds
// once the plan is near its limit ("9% left", "used up"). Pure, so the words are tested apart from the views.
import type {
    PlanUsageSummary,
    PlanWindow,
} from 'noclick';

const DAY_MS = 86_400_000;
const clock = (d: Date) =>
    d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();

/** When `at` comes, from `now`: a countdown later today ("in 38 min", "in 1 h 40 min"), else its day and time with
 *  AM/PM ("tomorrow 9:00 AM", "Thu 9:00 AM", "Nov 30 9:00 AM" a week or more away). */
export function resetWhen(at: Date, now: Date = new Date()): string {
    if (sameDay(at, now) || at.getTime() <= now.getTime()) {
        const minutes = Math.max(
            1,
            Math.ceil((at.getTime() - now.getTime()) / 60_000)
        );
        if (minutes < 60) return `in ${minutes} min`;
        const hours = Math.floor(minutes / 60);
        const rest = minutes % 60;
        return rest ? `in ${hours} h ${rest} min` : `in ${hours} h`;
    }
    return clockAt(at, now);
}

/** A moment as a clock with AM/PM: "3:20 PM" today, else with its day: ahead "tomorrow 9:00 AM", "Thu 9:00 AM", "Nov
 *  30 9:00 AM" a week or more away; past "yesterday 3:10 PM", else its date ("Nov 3, 3:10 PM"). */
export function clockAt(at: Date, now: Date = new Date()): string {
    if (sameDay(at, now)) return clock(at);
    if (at.getTime() < now.getTime())
        return sameDay(at, new Date(now.getTime() - DAY_MS))
            ? `yesterday ${clock(at)}`
            : `${at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${clock(at)}`;
    if (sameDay(at, new Date(now.getTime() + DAY_MS)))
        return `tomorrow ${clock(at)}`;
    const startOfToday = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate()
    ).getTime();
    const day =
        at.getTime() - startOfToday < 7 * DAY_MS
            ? at.toLocaleDateString('en-US', { weekday: 'short' })
            : at.toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
              });
    return `${day} ${clock(at)}`;
}

/** A window's line under its bar: "resets in 1 h 40 min", or once used up "back Thu 9:00 AM"; null with no reset. */
export function windowReset(
    w: Pick<PlanWindow, 'state' | 'resetsAt'>,
    now: Date = new Date()
): string | null {
    if (!w.resetsAt) return null;
    return `${w.state === 'used_up' ? 'back' : 'resets'} ${resetWhen(w.resetsAt, now)}`;
}

/** How much of a window is used: "62% used", "Used up". Never 100% before it's used up. */
export const windowUse = (w: Pick<PlanWindow, 'state' | 'used'>): string =>
    w.state === 'used_up'
        ? 'Used up'
        : `${Math.min(99, Math.round(w.used * 100))}% used`;

/** Whether a window is near or at its limit, so it reads in full ink. */
export const windowTight = (w: Pick<PlanWindow, 'state'>): boolean =>
    w.state === 'near' || w.state === 'used_up';

/** Every window of a plan, as its meter's title names them: "5-hour 91% used, resets in 1 h 40 min · Weekly 38%
 *  used, resets Thu 9:00 AM". */
export function windowsTitle(
    windows: readonly Pick<PlanWindow, 'label' | 'state' | 'used' | 'resetsAt'>[],
    now: Date = new Date()
): string {
    return windows
        .map((w) => [`${w.label} ${windowUse(w).toLowerCase()}`, windowReset(w, now)].filter(Boolean).join(', '))
        .join(' · ');
}

/** What the pill adds once the plan is near its limit for the pick: "9% left" (the tightest window's, rounded down),
 *  "used up"; null below it. */
export function planShortfall(
    usage: Pick<PlanUsageSummary, 'state' | 'tightest'> | null | undefined
): string | null {
    if (!usage) return null;
    if (usage.state === 'used_up') return 'used up';
    if (usage.state === 'near' && usage.tightest)
        return `${Math.floor(usage.tightest.left * 100 + 1e-9)}% left`;
    return null;
}
