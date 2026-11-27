// Where you are in Work, as the URL keeps it (so Back, a reload and a shared link all land in the same place): the
// space, which of its views (Home, Agents, DMs, Resources), and what's open there (a channel or DM, a thread beside
// it, an agent's session, its profile or machine, the members). One reader and one writer for every view.
import { useCallback, useMemo } from 'react';
import { useRouterSearchParams } from '@/lib/useRouterSearchParams';
import { standing } from '@/slots';
import { WORK_NOCLICK_CHANNEL, WORK_PARAMS } from './params';
import { WORK_ADDRESS } from './slots';

export type WorkView = 'home' | 'agents' | 'dms' | 'resources';
export const WORK_VIEWS: readonly WorkView[] = ['home', 'agents', 'dms', 'resources'];

/** What opens beside the main pane: the members (on one of their tabs), an agent's profile, or what your NoClick asked
 *  the space's. */
export type WorkPanel = 'people' | 'agents' | 'access' | 'profile' | 'questions';
const PANELS: readonly WorkPanel[] = ['people', 'agents', 'access', 'profile', 'questions'];

/** An agent's profile's tabs past its first: what triggers it, what it can use, its files, and every time it woke. */
export type ProfileTab = 'triggers' | 'tools' | 'files' | 'activity';
const PROFILE_TABS: readonly ProfileTab[] = ['triggers', 'tools', 'files', 'activity'];

/** Your own channels that sit in no space, as the space rail lists them. */
export const HOME_SPACE = 'home';
/** Home's list of every thread you follow, in a channel's place. */
export const THREADS = 'threads';
/** Home's template gallery, in a channel's place. */
export const TEMPLATES = 'templates';
/** The space's NoClick channel, whichever it is, in a channel's place (a link from Chat): opened once it's found. */
export const NOCLICK_HERE = WORK_NOCLICK_CHANNEL;
/** The Agents view's draft of a new agent, in an agent's place. */
export const NEW_AGENT = 'new';
/** The Resources view's overview, in a kind's place: a phone, whose list is the view, opens it as a screen of its own. */
export const RES_OVERVIEW = 'overview';

export interface WorkPlace {
    /** The space's id (`HOME_SPACE` for your channels in none); null until the page picks one. */
    space: string | null;
    view: WorkView;
    /** Home: a channel's id, `THREADS` or `TEMPLATES`; DMs: a DM's channel id. */
    channel: string | null;
    /** The message whose thread is open beside its channel. */
    thread: string | null;
    /** Agents: the agent whose session is open (or `NEW_AGENT`); anywhere: the agent whose profile is beside. */
    agent: string | null;
    panel: WorkPanel | null;
    /** The profile's tab (its first, Profile, when null). */
    profileTab: ProfileTab | null;
    /** In its Triggers tab: the trigger open, or `add` (`add:<kind>`) while one is being added. */
    trigger: string | null;
    /** The agent's machine page, in its session's place. */
    machine: boolean;
    /** On its machine page: the file open (absolute), which a link from the agent can name; one not there yet opens
     *  to be made. */
    file: string | null;
    /** In an agent's session: the subagent whose own screen is open over it. */
    subagent: string | null;
    /** The Resources view's own place (a kind, an item), its to read and write. */
    res: string | null;
    item: string | null;
    /** A space template's page of asks in the main pane: its address, or one of your repos by name. */
    template: string | null;
    /** Where that template goes: a space of yours (its workspace id); none, a new space. */
    into: string | null;
    /** In Home's template gallery: the template whose page is open, by its slug. */
    listing: string | null;
}

type Param = (typeof WORK_PARAMS)[number];

export function readPlace(params: URLSearchParams): WorkPlace {
    const show = params.get('show');
    const panel = params.get('panel');
    return {
        space: params.get('space'),
        view: (WORK_VIEWS as readonly string[]).includes(show ?? '') ? (show as WorkView) : 'home',
        channel: params.get('channel'),
        thread: params.get('thread'),
        agent: params.get('agent'),
        panel: (PANELS as readonly string[]).includes(panel ?? '') ? (panel as WorkPanel) : null,
        profileTab: (PROFILE_TABS as readonly string[]).includes(params.get('ptab') ?? '') ? (params.get('ptab') as ProfileTab) : null,
        trigger: params.get('trigger'),
        machine: params.get('machine') === '1',
        file: params.get('file'),
        subagent: params.get('sub'),
        res: params.get('res'),
        item: params.get('item'),
        template: params.get('template'),
        into: params.get('into'),
        listing: params.get('listing'),
    };
}

/** A change to where you are: a value sets its param, null clears it, undefined leaves it. */
export type PlaceChange = { [K in keyof WorkPlace]?: WorkPlace[K] | null };

export function withPlace(params: URLSearchParams, change: PlaceChange): URLSearchParams {
    const next = new URLSearchParams(params);
    const write = (key: Param, value: string | null | undefined) => {
        if (value === undefined) return;
        if (value === null || value === '') next.delete(key);
        else next.set(key, value);
    };
    write('space', change.space);
    write('show', change.view === 'home' ? null : change.view);
    write('channel', change.channel);
    write('thread', change.thread);
    write('agent', change.agent);
    write('panel', change.panel);
    write('ptab', change.profileTab);
    write('trigger', change.trigger);
    write('machine', change.machine === undefined ? undefined : change.machine ? '1' : null);
    // A file is open only on the machine page: leaving it closes the file too.
    write('file', change.file !== undefined ? change.file : change.machine === false ? null : undefined);
    write('sub', change.subagent);
    write('res', change.res);
    write('item', change.item);
    write('template', change.template);
    write('into', change.into);
    // A template's page is open only in the gallery: leaving it for a channel closes the page too.
    write('listing', change.listing !== undefined ? change.listing : change.channel !== undefined ? null : undefined);
    return next;
}

/** A space template's page of asks in Work, from outside it (a gallery's card, a Deploy on NoClick link): aimed at
 *  `spaceId` (a space of yours) where you came from one, else at a new space. */
export const templatePlace = (source: string, spaceId?: string | null) => withPlace(new URLSearchParams(), { template: source, into: spaceId ?? null, space: spaceId ?? null });

/** Open a space template's page of asks in Work. */
export function openTemplateInWork(source: string, spaceId?: string | null): void {
    standing(WORK_ADDRESS).go(templatePlace(source, spaceId));
}

/** Open an agent in Work from outside it (a card, Resources): its session, with its profile beside, where it's
 *  changed; in your account's home, which lists every agent of the account. Whatever else Work had open closes. Work
 *  is where its host says (`WORK_ADDRESS`). */
export function openAgentInWork(agentId: string): void {
    standing(WORK_ADDRESS).go(withPlace(new URLSearchParams(), { space: HOME_SPACE, view: 'agents', agent: agentId, panel: 'profile' }));
}

/** Open a file on an agent's machine page from outside it (a question asking for it): one not there yet opens to be
 *  made. */
export function openMachineFile(agentId: string, path: string): void {
    standing(WORK_ADDRESS).go(withPlace(new URLSearchParams(), { space: HOME_SPACE, view: 'agents', agent: agentId, machine: true, file: path }));
}

/** A channel in Work from outside it, as `navigateToWorkChannel` has it: the channel alone, its space read from it, so
 *  a space left in the URL can't hide it. */
const channelPlace = (channelId: string) => withPlace(new URLSearchParams(), { channel: channelId });

/** A link to a channel in Work, as an address. */
export const channelHref = (channelId: string) => standing(WORK_ADDRESS).href(channelPlace(channelId));

/** Open a channel in Work from outside it (the Chat page); whatever else Work had open closes. */
export function openChannelInWork(channelId: string): void {
    standing(WORK_ADDRESS).go(channelPlace(channelId));
}

/** Where you are, and the one way to move: each move is a history entry (so Back undoes it) unless `replace`. Read from
 *  the URL the router is on, not the one last drawn, so Work opened from another page never reads (and writes over)
 *  that page's. */
export function useWorkPlace(): [WorkPlace, (change: PlaceChange, options?: { replace?: boolean }) => void] {
    const [params, setParams] = useRouterSearchParams();
    const place = useMemo(() => readPlace(params), [params]);
    const go = useCallback(
        (change: PlaceChange, options: { replace?: boolean } = {}) => setParams((prev) => withPlace(prev, change), { replace: options.replace }),
        [setParams]
    );
    return [place, go];
}
