// What Work makes of an agent's triggers (GET /v1/agents/{id}/triggers) and the wake-ups it set itself: one list, each
// in the agent's own words, grouped by what needs you, its status in a few words and what you can do with it. The
// platform's view says each one's state, fix and actions; a view from before it said them is read from its `status`
// and `error`, and offers only what its definition takes. Plus the plain-words schedule reader the add flow uses.
import type { AgentTrigger, TriggerAction, TriggerFix, TriggerSummary, Wakeup } from 'noclick';
import { describeCronIn } from '@/lib/scheduleFormat';
import { agoText } from '../agents/states';

export type TriggerKind = AgentTrigger['kind'] | 'wakeup';
export type TriggerState = 'live' | 'paused' | 'stopped';

/** One trigger as Work shows it: an agent's trigger, or a one-off wake-up it set itself. */
export interface TriggerItem {
    id: string;
    kind: TriggerKind;
    spec: Record<string, unknown>;
    /** An app event's in a few words, the platform's ("Messages to +91 98765 43210"). */
    title: string | null;
    /** What an app event hears through: its app, the account, what it hears, whether that account is linked. */
    summary: TriggerSummary | null;
    state: TriggerState;
    /** Paused on its own, the agent running on. */
    pausedItself: boolean;
    /** Why it isn't live, in the platform's words. */
    reason: string | null;
    fix: TriggerFix | null;
    nextAt: Date | null;
    lastAt: Date | null;
    setBy: 'person' | 'agent' | 'automation';
    readOnly: boolean;
    /** What it takes: the view's own, plus `cancel` for a wake-up. */
    actions: (TriggerAction | 'cancel')[];
    /** A webhook's URL. */
    url: string | null;
    /** A turn it started is queued or running. */
    running: boolean;
    trigger?: AgentTrigger;
    wakeup?: Wakeup;
}

const text = (spec: Record<string, unknown>, key: string) => (typeof spec[key] === 'string' ? (spec[key] as string) : '');

/** A trigger as the platform's view says it, or (a view from before it said so) as its `status` and `error` say. */
export function itemOf(t: AgentTrigger, agentPaused: boolean): TriggerItem {
    const said = 'state' in t.raw;
    const state: TriggerState = said ? t.state : agentPaused || t.status === 'paused' ? 'paused' : t.status === 'error' ? 'stopped' : 'live';
    return {
        id: t.id,
        kind: t.kind,
        spec: t.spec as Record<string, unknown>,
        title: t.title,
        summary: t.summary,
        state,
        pausedItself: t.paused,
        reason: said ? t.reason : t.error,
        fix: said ? t.fix : agentPaused ? { action: 'resume_agent' } : null,
        nextAt: t.nextRunAt ?? t.nextRun,
        lastAt: t.lastFiredAt,
        setBy: said ? t.setBy.kind : 'person',
        readOnly: said ? t.readOnly : !t.defined,
        actions: Array.isArray(t.raw.actions) ? t.actions : t.defined ? ['test', 'update', 'remove'] : [],
        url: t.url,
        running: t.raw.running === true,
        trigger: t,
    };
}

/** A one-off wake-up it set itself: read-only, cancelled rather than removed. Recurring ones are its routines, which
 *  the triggers list carries. */
export function wakeupItem(w: Wakeup, agentPaused: boolean): TriggerItem {
    return {
        id: `wakeup:${w.id}`,
        kind: 'wakeup',
        spec: { note: w.note, conversation: w.conversation },
        title: null,
        summary: null,
        state: agentPaused ? 'paused' : 'live',
        pausedItself: false,
        reason: null,
        fix: agentPaused ? { action: 'resume_agent' } : null,
        nextAt: w.at,
        lastAt: null,
        setBy: w.source === 'wake_me' ? 'agent' : 'person',
        readOnly: true,
        actions: ['cancel'],
        url: null,
        running: false,
        wakeup: w,
    };
}

/** What needs you first (stopped), then the rest as they were. */
export const byAttention = (items: readonly TriggerItem[]) => [...items].sort((a, b) => Number(b.state === 'stopped') - Number(a.state === 'stopped'));

/** The soonest a live one runs: a schedule's, a routine's, a wake-up's. */
export function nextRun(items: readonly TriggerItem[]): { item: TriggerItem; at: Date } | null {
    const due = items.filter((i) => i.state === 'live' && i.nextAt).map((i) => ({ item: i, at: i.nextAt! }));
    return due.sort((a, b) => a.at.getTime() - b.at.getTime())[0] ?? null;
}

// ── in its words ────────────────────────────────────────────────────────────

/** NoClick's own events a person would pick (GET /v1/events/types), each as it reads in a sentence. */
export const PLATFORM_EVENTS: { type: string; when: string; detail: string }[] = [
    { type: 'workflow.run.failed', when: 'a run fails', detail: 'Any automation’s run, with its error' },
    { type: 'agent.asked_owner', when: 'an agent asks you something', detail: 'Another agent’s question waiting on you' },
    { type: 'deployment.failed', when: 'a deploy fails', detail: 'One of your websites' },
    { type: 'payment.completed', when: 'a payment comes in', detail: 'Through one of your payment links' },
    { type: 'connection.disconnected', when: 'an account disconnects', detail: 'Any connected account stops working' },
    { type: 'spend.cap_reached', when: 'your spending cap is reached', detail: 'The account’s monthly cap' },
];

/** Events NoClick sets its own assistant to hear (an app's live editing), never offered to pick, read the same way. */
const NOCLICKS_EVENTS: typeof PLATFORM_EVENTS = [
    { type: 'live.deploy_failed', when: 'a live edit’s deploy fails', detail: 'An app edited live that didn’t deploy' },
    { type: 'live.session_failed', when: 'a live editing session fails', detail: 'An app’s live editing that stopped with an error' },
];

/** A NoClick event in words, where there are any for it. */
export const platformEvent = (type: string) => PLATFORM_EVENTS.find((p) => p.type === type) ?? NOCLICKS_EVENTS.find((p) => p.type === type);

const clock = (d: Date) => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** "9:00 AM" today, "Fri 9:00 AM" after: when it next runs, in a few words. */
export const shortWhen = (d: Date, now = new Date()) => (sameDay(d, now) ? clock(d) : `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${clock(d)}`);

/** "today at 9:00 AM", "tomorrow at 9:00 AM", "Thu, Nov 13 at 9:00 AM". */
export function longWhen(d: Date, now = new Date()) {
    const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(d) - day(now)) / 86_400_000);
    const label = diff === 0 ? 'today' : diff === 1 ? 'tomorrow' : d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    return `${label} at ${clock(d)}`;
}

const lowerFirst = (s: string) => (s ? s.charAt(0).toLowerCase() + s.slice(1) : s);
const upperFirst = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const stripDot = (s: string) => s.trim().replace(/[.!]+$/, '');

/** "issue_opened" → "Issue opened". */
export const eventLabel = (name: string) => upperFirst(name.replace(/^on[\s_]+/i, '').replace(/_/g, ' ').trim().toLowerCase());

/** What the sentence needs from outside the trigger: an app event's app, named as NoClick names it. */
export interface Names {
    appOf: (connection: string) => string;
}

/** When it wakes, as a clause: "Weekdays at 9:00 AM", "When GitHub says “Issue opened” in noclickapp/web". */
export function whenOf(item: TriggerItem, names: Names): string {
    const s = item.spec;
    switch (item.kind) {
        case 'cron':
        case 'routine':
            // `user`: the reader's own clock, so it names none.
            return describeCronIn(text(s, 'cron'), text(s, 'tz') === 'user' ? Intl.DateTimeFormat().resolvedOptions().timeZone : text(s, 'tz')) ?? 'On a schedule';
        case 'event': {
            if (item.title) return item.title;
            // A switch ("true") narrows nothing a person would name.
            const filters = Object.values((s.filters ?? {}) as Record<string, unknown>)
                .map(String)
                .filter((v) => v && !/^(true|false)$/i.test(v));
            return `When ${names.appOf(text(s, 'connection'))} says “${eventLabel(text(s, 'event'))}”${filters.length ? ` in ${filters.join(', ')}` : ''}`;
        }
        case 'webhook':
            return `When something posts to my “${text(s, 'name')}” webhook`;
        case 'platform':
            return `When ${platformEvent(text(s, 'type'))?.when ?? text(s, 'type')}`;
        case 'queue':
            return `When something lands on my “${text(s, 'queue')}” queue`;
        case 'email':
            return `When ${text(s, 'senders') === 'owner' ? 'you email' : 'someone emails'} ${text(s, 'address') || 'my inbox'}`;
        case 'call':
            return `When someone calls ${text(s, 'number') || 'my number'}`;
        case 'channel':
            return text(s, 'mode') === 'all' ? `When anyone writes in #${text(s, 'name')}` : `When someone @mentions me in #${text(s, 'name')}`;
        case 'approval':
            return 'When you answer a call I held for you';
        case 'app':
            return `When the “${text(s, 'name') || 'trigger'}” step of my automation fires`;
        case 'wakeup':
            return item.nextAt ? upperFirst(longWhen(item.nextAt)) : 'Later';
    }
}

/** Its whole line, in its own words: "Weekdays at 9:00 AM, I’ll go through the support inbox." */
export function sentenceOf(item: TriggerItem, names: Names): string {
    // An app event the platform titles reads as what arrives where, and what of it it hears.
    if (item.title) return item.summary?.hears ? `${item.title} · ${item.summary.hears}` : item.title;
    const then = text(item.spec, 'message') || text(item.spec, 'note');
    return `${whenOf(item, names)}, I’ll ${then ? lowerFirst(stripDot(then)) : 'pick it up'}.`;
}

/** A titled app event's line under its title, never "Live" (its group says so): what keeps it from hearing anything
 *  (`warn`, then what fixes it), that it's paused on its own, or what it hears. Null for a trigger with no title. */
export function sourceLine(item: TriggerItem): { warn: string | null; text: string | null } | null {
    const s = item.summary;
    if (!item.title || !s) return null;
    const hears = s.hears ?? s.app;
    if (item.state === 'stopped') return s.problem ? { warn: s.problem, text: s.remedy } : { warn: item.reason ?? 'Stopped', text: null };
    if (item.state === 'paused' && item.pausedItself) return { warn: null, text: ['Paused', hears].filter(Boolean).join(' · ') };
    return { warn: null, text: hears };
}

/** Its status in a few words: what's next, when it last ran, or that it's paused or set itself. */
export function statusOf(item: TriggerItem, now = new Date()): { text: string; tone: 'ok' | 'paused' | 'stopped' } {
    if (item.state === 'stopped') return { text: 'Stopped', tone: 'stopped' };
    if (item.state === 'paused') return { text: 'Paused', tone: 'paused' };
    // A wake-up says its time in its sentence.
    if (item.kind === 'wakeup') return { text: 'Set itself', tone: 'ok' };
    if (item.nextAt) return { text: `Next ${shortWhen(item.nextAt, now)}`, tone: 'ok' };
    if (!item.lastAt) return { text: 'Hasn’t run yet', tone: 'ok' };
    return { text: `Last ran ${agoText(now.getTime() - item.lastAt.getTime())}`, tone: 'ok' };
}

/** The fix's button: "Reconnect Stripe", "Resume", "Open in the app". */
export function fixLabel(fix: TriggerFix, names: Names): string {
    switch (fix.action) {
        case 'connect':
            return `Reconnect ${names.appOf(fix.connection ?? '')}`;
        case 'replace':
            return `Use another ${names.appOf(fix.connection ?? '')} account`;
        case 'open_in_app':
            return 'Open in the app';
        default:
            return 'Resume';
    }
}

// ── schedules in plain words ────────────────────────────────────────────────

const DAY_NAMES = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
const DAY_LABEL = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const at = (h: number, m: number) => clock(new Date(2000, 0, 1, h, m));
const listDays = (days: number[]) => {
    const names = days.map((d) => DAY_LABEL[d]);
    return names.length <= 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
};
const ordinal = (n: number) => `${n}${n % 10 === 1 && n !== 11 ? 'st' : n % 10 === 2 && n !== 12 ? 'nd' : n % 10 === 3 && n !== 13 ? 'rd' : 'th'}`;

export interface Schedule {
    /** As it reads back: "Every weekday at 9:00 AM". */
    words: string;
    /** The five-field cron the API takes. */
    expr: string;
    /** Its next times from `from`, in this browser's clock. */
    next: (n: number, from?: Date) => Date[];
    /** A time it assumed, when it wasn't given one. */
    assumed?: string;
}

/** Reads "every weekday at 9", "mondays and thursdays at 8:30am", "every day at 6pm", "every 15 minutes", "every hour"
 *  and "every month on the 1st at 9" into a schedule; null for words it can't read. */
export function readSchedule(input: string): Schedule | null {
    const s = input.toLowerCase().replace(/\s+/g, ' ').trim();
    if (!s) return null;
    if (/\b(every hour|hourly)\b/.test(s) && !/every \d/.test(s)) return readSchedule('every 1 hour');
    const every = s.match(/every (\d+) ?(minutes?|mins?|m|hours?|hrs?|h)\b/);
    if (every) {
        const n = Number(every[1]);
        const hours = every[2].startsWith('h');
        if (!n || (hours ? n > 23 : n > 59)) return null;
        return {
            words: `Every ${n === 1 ? (hours ? 'hour' : 'minute') : `${n} ${hours ? 'hours' : 'minutes'}`}`,
            expr: hours ? `0 ${n === 1 ? '*' : `*/${n}`} * * *` : `*/${n} * * * *`,
            next: (count, from = new Date()) => {
                const out: Date[] = [];
                const t = new Date(from);
                t.setSeconds(0, 0);
                while (out.length < count) {
                    t.setMinutes(t.getMinutes() + 1);
                    if (hours ? t.getMinutes() === 0 && t.getHours() % n === 0 : t.getMinutes() % n === 0) out.push(new Date(t));
                }
                return out;
            },
        };
    }
    const time = [...s.matchAll(/(?:at )?\b(\d{1,2})(?::(\d{2}))? ?(am|pm|a\.m\.|p\.m\.)?(?=\b|$)/g)].filter((m) => m[2] || m[3] || /at \d/.test(m[0])).at(-1);
    let h = 9;
    let m = 0;
    let assumed: string | undefined;
    if (time) {
        h = Number(time[1]);
        m = Number(time[2] ?? 0);
        const ampm = time[3]?.[0];
        if (ampm === 'p' && h < 12) h += 12;
        if (ampm === 'a' && h === 12) h = 0;
        if (h > 23 || m > 59) return null;
    } else assumed = at(9, 0);
    const monthly = s.match(/(?:every month|monthly)(?: on the (\d{1,2})(?:st|nd|rd|th)?)?/) ?? s.match(/on the (\d{1,2})(?:st|nd|rd|th)? of (?:every|each) month/);
    if (monthly) {
        const dom = Number(monthly[1] ?? 1);
        if (dom < 1 || dom > 28) return null;
        return {
            words: `On the ${ordinal(dom)} of every month at ${at(h, m)}`,
            expr: `${m} ${h} ${dom} * *`,
            assumed,
            next: (count, from = new Date()) => {
                const out: Date[] = [];
                const t = new Date(from.getFullYear(), from.getMonth(), dom, h, m);
                if (t <= from) t.setMonth(t.getMonth() + 1);
                while (out.length < count) {
                    out.push(new Date(t));
                    t.setMonth(t.getMonth() + 1);
                }
                return out;
            },
        };
    }
    let days: number[] | null = null;
    if (/week ?days?|work ?days?|mon(day)?s? ?(-|to|through) ?fri(day)?s?/.test(s)) days = [1, 2, 3, 4, 5];
    else if (/weekends?/.test(s)) days = [0, 6];
    else if (/every day|daily|each day|every morning|every evening|every night/.test(s)) days = [0, 1, 2, 3, 4, 5, 6];
    else {
        const named = DAY_NAMES.map((d, i) => (new RegExp(`\\b${d.slice(0, 3)}(${d.slice(3)})?s?\\b`).test(s) ? i : -1)).filter((i) => i >= 0);
        if (named.length) days = named;
        else if (time) days = [0, 1, 2, 3, 4, 5, 6];
    }
    if (!days) return null;
    const dayWords = days.length === 7 ? 'Every day' : days.join() === '1,2,3,4,5' ? 'Every weekday' : days.join() === '0,6' ? 'Every weekend day' : `Every ${listDays(days)}`;
    return {
        words: `${dayWords} at ${at(h, m)}`,
        expr: `${m} ${h} * * ${days.length === 7 ? '*' : days.join(',')}`,
        assumed,
        next: (count, from = new Date()) => {
            const out: Date[] = [];
            const t = new Date(from.getFullYear(), from.getMonth(), from.getDate(), h, m);
            for (let i = 0; out.length < count && i < 400; i++) {
                if (days!.includes(t.getDay()) && t > from) out.push(new Date(t));
                t.setDate(t.getDate() + 1);
            }
            return out;
        },
    };
}
