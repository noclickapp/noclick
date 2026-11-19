// What Work remembers on this device: the space you were last in, and what you last had open in each of its views
// (Home's channel and thread, DMs' DM, Agents' agent with its profile, Resources' kind and item), so
// Work reopens where you left it and each view reopens where you left it in that space; and when you last opened each
// channel, which the Chat page's card about a channel folds by where the platform can't say (a channel with nothing in
// it to read). Lost (a private window, cleared storage) it simply opens on the first.
import { NEW_AGENT, THREADS, type WorkPlace, type WorkView } from './place';

const SPACE_KEY = 'nc-work-space';
/** Each space's views' spots. Named when it held Home's channel alone, which an older value still is. */
const VIEWS_KEY = 'nc-work-channels';
const OPENED_KEY = 'nc-work-opened';
/** The channels whose last opening is kept: the newest. */
const OPENED_KEPT = 200;

function read(key: string): string | null {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

function write(key: string, value: string): void {
    try {
        window.localStorage.setItem(key, value);
    } catch {
        // Not remembered this time; Work still opens.
    }
}

export const lastSpace = (): string | null => read(SPACE_KEY);

export function rememberSpace(id: string): void {
    if (read(SPACE_KEY) !== id) write(SPACE_KEY, id);
}

function record<T>(key: string): Record<string, T> {
    try {
        const parsed: unknown = JSON.parse(read(key) ?? '{}');
        return parsed && typeof parsed === 'object' ? (parsed as Record<string, T>) : {};
    } catch {
        return {};
    }
}

/** What a view had open, as the URL named it: Home's channel (or `THREADS`) and thread, DMs' DM (`channel`), Agents'
 *  agent and whether its profile was beside, Resources' kind (`res`) and item. Empty: Resources' overview. */
export interface Spot {
    channel?: string;
    thread?: string;
    agent?: string;
    profile?: true;
    res?: string;
    item?: string;
}

type Views = Partial<Record<WorkView, Spot>>;

/** Only what's set, in one order, so two spots of the same place read the same. */
function spot(fields: { [K in keyof Spot]: Spot[K] | null | false | undefined }): Spot {
    const kept: Spot = {};
    for (const key of ['channel', 'thread', 'agent', 'profile', 'res', 'item'] as const) {
        const value = fields[key];
        if (value) (kept as Record<string, unknown>)[key] = value;
    }
    return kept;
}

function viewsOf(all: Record<string, unknown>, space: string): Views {
    const kept = all[space];
    if (typeof kept === 'string') return { home: { channel: kept } };
    return kept && typeof kept === 'object' ? (kept as Views) : {};
}

/** What was last open in `view` in `space`, or null where nothing was. */
export const lastSpot = (space: string, view: WorkView): Spot | null => viewsOf(record(VIEWS_KEY), space)[view] ?? null;

/** The channel last open in a space's Home (or `THREADS`), or null. */
export const lastChannel = (space: string): string | null => lastSpot(space, 'home')?.channel ?? null;

export function rememberSpot(space: string, view: WorkView, open: Spot): void {
    const all = record<unknown>(VIEWS_KEY);
    const views = viewsOf(all, space);
    const kept = spot(open);
    const was = views[view];
    if (was && JSON.stringify(spot(was)) === JSON.stringify(kept)) return;
    write(VIEWS_KEY, JSON.stringify({ ...all, [space]: { ...views, [view]: kept } }));
}

/** What `place` has open in its view that the view can reopen: Home's channel (or its threads) and thread, DMs' DM,
 *  Agents' agent with its profile, Resources' kind and item (none: its overview). Null where it has
 *  nothing open (a phone's list, a new agent's draft). `open`: the channel the page opened, as it found it. */
export function spotOf(place: WorkPlace, open: { id: string; kind?: string } | null): Spot | null {
    switch (place.view) {
        case 'home':
            if (place.channel === THREADS) return { channel: THREADS };
            return open && open.kind !== 'dm' ? spot({ channel: open.id, thread: place.thread }) : null;
        case 'dms':
            return open?.kind === 'dm' ? { channel: open.id } : null;
        case 'agents':
            return place.agent && place.agent !== NEW_AGENT ? spot({ agent: place.agent, profile: place.panel === 'profile' }) : null;
        case 'resources':
            return spot({ res: place.res, item: place.item });
    }
}

/** When you last opened `channelId` in Work on this device (ms), or null. */
export const openedAt = (channelId: string): number | null => record<number>(OPENED_KEY)[channelId] ?? null;

export function rememberOpened(channelId: string): void {
    const kept = Object.entries({ ...record<number>(OPENED_KEY), [channelId]: Date.now() })
        .sort(([, a], [, b]) => b - a)
        .slice(0, OPENED_KEPT);
    write(OPENED_KEY, JSON.stringify(Object.fromEntries(kept)));
}
