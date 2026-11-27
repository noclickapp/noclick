// Work: where your agents and the people you work with talk, laid out as Slack is. On a laptop: the app's sidebar
// folded to its icons, the spaces' rail, the views' rail (Home, Agents, DMs, Resources), the view's list (resizable),
// what's open, and a panel beside it (a thread, an agent's profile, the members; resizable). On a phone: the view's
// list over a bar of the views, and whatever opens takes the whole screen with the bar's way back. Where you are lives
// in the URL (place.ts). Your own spaces read through the dashboard's client; a space you joined in another account
// through a session acting as you there, read through your eyes. Every view follows the account's frames.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { BriefcaseBusiness, Hash, MessagesSquare, UsersRound } from 'lucide-react';
import { toast } from 'sonner';
import type { AccountMenuUser } from '@/ui/accountParts';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { authorMember } from '@/screens/channels/model';
import { NewChannelDialog } from '@/screens/channels/NewChannelDialog';
import type { Channel, ChannelAuthor, ChannelMember, PersonChoice } from '@/screens/channels/types';
import { WorkLoading, WorkNotice } from './notices';
import { TooltipProvider } from '@/ui/tooltip';
import { changeOf, platformTransport, sdkTyping, typingChangeOf, type Perspective, type PlatformTransport } from '@/screens/channels/sdkTransport';
import { standing } from '@/slots';
import { Channel as PlatformChannel, type NoClick } from 'noclick';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useChannels, type Channels } from '@/screens/channels/useChannels';
import { useIntent } from '@/ui/useIntent';
import { prefetchV1 } from '@/sdk/useV1';
import { AgentRoles, isSpaceNoClick, nameOf, SpaceNoClicksContext, statesKey, useAgents, useAgentStates, useHelperIds, useNoClickId, useSpaceNoClicks } from './agents/reads';
import { readAgentStates } from './agents/states';
import { ChannelPane } from './channels/ChannelPane';
import { useDrafts } from './channels/drafts';
import { platformShelf } from './channels/platformShelf';
import { ThreadPanel } from './channels/ThreadPanel';
import { useWorkClient, WorkClientContext } from './client';
import { byNewest, DmsList, type DmRow } from './home/DmsList';
import { HomeList } from './home/HomeList';
import { threadsKey, ThreadsPane, useFollowedThreads } from './home/ThreadsPane';
import { useWorkFrames } from '@/sdk/live';
import { WorkNavContext, type WorkNav } from './nav';
import { AgentConversation, AgentOpening, AgentProfile, AgentsList, MachinePage, NewAgent, prefetchConversation, SpaceResourcesNav, SpaceResourcesPane, useFollowSessions, useSessions } from './parts';
import { InviteDialog } from './people/InviteDialog';
import { peopleKey, readPeople, useSpacePeople } from './people/members';
import { MembersPanel, presenceOf, roleLabel } from './people/MembersPanel';
import { HOME_SPACE, NEW_AGENT, NOCLICK_HERE, TEMPLATES, THREADS, useWorkPlace, type WorkPlace, type WorkView } from './place';
import { SpaceRail, ViewBar, ViewRail, type ViewCounts } from './rails';
import { lastChannel, lastSpace, lastSpot, rememberOpened, rememberSpace, rememberSpot, spotOf, type Spot } from './remember';
import { AgentsEmpty, DmsEmpty, HomeEmpty } from './empty';
import { SpaceDialog } from './SpaceDialog';
import { dropAccountNoClick, EARLIER_NOCLICK_CHANNEL, giveSpaceNoClick, homeHoldsNoClick, isNoClickChannel, makeHomeNoClickChannel, NOCLICK_CHANNEL, openNoClickChannel, spaceNoClickFixes, useOwnSpaceNoClicks, useSpaceNoClick } from './intro';
import { ASKED_TITLE, SpaceQuestionsPanel, useSpaceQuestions } from './questions';
import { usePickerAgents } from './channels/pickerAgents';
import { SaveTemplateDialog } from './SaveTemplateDialog';
import { AddTemplatePage } from './templates/AddTemplatePage';
import { TemplatesPane } from './templates/TemplatesPane';
import { SpaceHeader } from './SpaceHeader';
import { ArchivedBanner, SpaceSettingsDialog, unarchiveSpace, type SpaceAsk } from './spaceSettings';
import { isSpaceKind, kindOf, prefetchSpaceShare } from './resources/space/data';
import { homeSpace, useSpaceClient, useSpaces, type Spaces, type WorkSpace } from './spaces';
import { WorkViewerContext, type WorkViewer } from './viewer';
import { useWork } from './context';
import { JOINED_TYPING } from './slots';
import { ListColumn, useFoldedByChoice, useListRoom, useMeasuredWidth } from './listRail';
import { LIST_COLUMN, PanelFrame } from './ui';
import { ownerOnlyWhy, useOwnerOnly } from '@/screens/console/ownerOnly';

const byAge = (a: Channel, b: Channel) => a.createdAt.localeCompare(b.createdAt);
/** The space a channel is in: your personal space's, in no workspace or (a DM there) in its shared workspace, is home. */
const spaceIdOf = (c: Channel, personalId: string | null) => (!c.workspaceId || c.workspaceId === personalId ? HOME_SPACE : c.workspaceId);

/** The other person in a DM. */
function otherIn(channel: Channel): ChannelMember | null {
    return channel.members.find((m) => m.kind === 'human') ?? null;
}

/** One transport per client and perspective for the page's life, so what it held survives Work being left and opened
 *  again (useChannels keeps it per transport). */
const transports = new WeakMap<NoClick, Map<string, PlatformTransport>>();

export function transportFor(client: NoClick, key: string, person: (Perspective & { workspaceId: string }) | undefined): PlatformTransport {
    let byKey = transports.get(client);
    if (!byKey) transports.set(client, (byKey = new Map()));
    let transport = byKey.get(key);
    if (!transport) byKey.set(key, (transport = platformTransport(client, person ? { sendTyping: standing(JOINED_TYPING)(client), person } : { sendTyping: sdkTyping(client) })));
    return transport;
}

/** Your account's own perspective's transport key. */
export const OWN = 'own';

/** The channels a client reads (your account's own, or a joined space's through your eyes), followed live. */
function useClientChannels(client: NoClick, space: WorkSpace | null, openId: string | null): { transport: PlatformTransport; channels: Channels } {
    const person = space && !space.own && space.workspaceId && space.userId ? { me: space.userId, ownerName: space.accountName ?? 'The owner', workspaceId: space.workspaceId } : undefined;
    const key = person ? `${person.workspaceId}:${person.me}:${person.ownerName}` : OWN;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` names the perspective
    const transport = useMemo(() => transportFor(client, key, person), [client, key]);
    useWorkFrames('platform:channel', (frame) => transport.deliver(changeOf(frame)));
    useWorkFrames('platform:channel_typing', (frame) => transport.deliver(typingChangeOf(frame)));
    // The stream lost its place: the channels read everything they hold again (their own timer covers a backstop).
    useWorkFrames('reset', (reset) => reset.why === 'stream' && transport.deliver({ kind: 'reset' }));
    return { transport, channels: useChannels(transport, openId) };
}

/** The channel a laptop opens in a space's Home: where you last were there, else its oldest open one. */
function openingChannel(spaceChannels: Channel[], spaceId: string): Channel | null {
    return spaceChannels.find((c) => c.id === lastChannel(spaceId)) ?? spaceChannels.find((c) => c.status !== 'closed') ?? spaceChannels[0] ?? null;
}

/** The DM a laptop opens in a space's DMs: the one you last had open there, else the newest. */
function openingDm(dms: Channel[], spaceId: string): Channel | null {
    const last = lastSpot(spaceId, 'dms')?.channel;
    return dms.find((c) => c.id === last) ?? [...dms].sort(byNewest)[0] ?? null;
}

/** What's open in Home or DMs, for its history to load. */
const openIdOf = (place: WorkPlace) =>
    (place.view === 'home' || place.view === 'dms') && place.channel && place.channel !== THREADS && place.channel !== TEMPLATES && place.channel !== NOCLICK_HERE ? place.channel : null;

/** The personal space's NoClick channel, made the first time Work finds none there (`makeHomeNoClickChannel`) once
 *  it's `ready` (the spaces read, so where Work opens is settled), through the page's channels so it's listed the
 *  moment it's made (its frame then confirms it), then `onMade` with it. True while Home's channels can't be shown as
 *  they are: NoClick's own agent isn't read yet (`noclick` undefined while `reading`), or its channel is missing and on
 *  its way. A failure says so and stops the wait. */
function useHomeNoClickChannel(client: NoClick, own: Channels, ready: boolean, homeName: string, noclick: string | null | undefined, reading: boolean, onMade: (id: string) => void): boolean {
    const missing = ready && !own.error && typeof noclick === 'string' && !homeHoldsNoClick(own.channels, noclick);
    // The make answered (made, found outside the list read, or failed): Home shows what it has.
    const [answered, setAnswered] = useState(false);
    const latest = useRef({ onMade, create: own.createChannel });
    latest.current = { onMade, create: own.createChannel };
    useEffect(() => {
        if (!missing || typeof noclick !== 'string') return;
        let live = true;
        const start = () => {
            setAnswered(false);
            makeHomeNoClickChannel(client, noclick, (input) => latest.current.create(input)).then(
                (made) => {
                    if (!live) return;
                    setAnswered(true);
                    if (made) latest.current.onMade(made.id);
                },
                (e: unknown) => {
                    if (!live) return;
                    setAnswered(true);
                    toast.error(`Couldn’t start #${NOCLICK_CHANNEL} in ${homeName}`, { description: errorText(e), duration: Infinity, action: { label: 'Try again', onClick: start } });
                }
            );
        };
        start();
        return () => {
            live = false;
        };
    }, [missing, client, homeName, noclick]);
    return ready && !own.error && ((noclick === undefined && reading) || (missing && !answered));
}

/** A space's channels from before each space had its own NoClick hold the account's, silent there now: when the space
 *  opens (one of the account's own), its NoClick channel takes the space's NoClick, and once a channel holds both, the
 *  account's leaves it. Each change once a session. */
function useSpaceNoClickJoins(client: NoClick, space: WorkSpace, channels: Channel[]): void {
    const noclick = useNoClickId();
    const workspaceId = space.own ? space.workspaceId : null;
    const ours = useSpaceNoClicks().of.get(workspaceId ?? '');
    const fixes = workspaceId && noclick && ours ? spaceNoClickFixes(channels, workspaceId, noclick, ours.agentId) : null;
    const key = fixes ? JSON.stringify(fixes) : '';
    useEffect(() => {
        if (!key || !ours) return;
        const { add, drop } = JSON.parse(key) as ReturnType<typeof spaceNoClickFixes>;
        for (const id of add) giveSpaceNoClick(client, id, ours.agentId).catch((e: unknown) => console.warn(`[work] the space's NoClick couldn't join ${id}:`, e));
        for (const d of drop) dropAccountNoClick(client, d.channel, d.member).catch((e: unknown) => console.warn(`[work] NoClick's own couldn't leave ${d.channel}:`, e));
    }, [client, key, ours]);
}

export function Work({ user }: { user: AccountMenuUser }) {
    const client = useWorkClient();
    const [place, go] = useWorkPlace();
    useFollowSessions();
    const spaces = useSpaces();
    // A link that names a channel and no space is your own account's.
    const chosen = spaces.spaces.find((s) => s.id === place.space) ?? (place.channel && !place.space ? null : (spaces.spaces.find((s) => s.id === lastSpace()) ?? null));
    const joined = chosen && !chosen.own ? chosen : null;
    const own = useClientChannels(client, null, joined ? null : openIdOf(place));

    // Your account's own home is always first on the rail: your channels in no space, and every agent of the account
    // (one in no space is reached only here; NoClick's own is the Chat page's). With nothing in it but its NoClick
    // channel, Work opens on your first space, and with no space either, on that channel.
    const home = useMemo(
        () => ({ ...homeSpace(user.display_name?.trim() || user.email.split('@')[0] || 'Your channels', user.avatar_url), ...(spaces.personalId ? { sharedId: spaces.personalId } : {}) }),
        [user, spaces.personalId]
    );
    const ownOpenChannels = useMemo(() => own.channels.channels.filter((c) => c.status !== 'closed'), [own.channels.channels]);
    const all = useMemo(() => [home, ...spaces.spaces], [spaces.spaces, home]);
    const noclick = useNoClickId();
    const readingAgents = useAgents().loading;
    const spaceNoClicks = useOwnSpaceNoClicks(spaces.spaces);
    // Its NoClick channel (by its name until the agents are read) doesn't make it the space to open on.
    const homeUsed = ownOpenChannels.some((c) => !c.workspaceId && !(noclick === undefined ? c.name === NOCLICK_CHANNEL : c.members.some((m) => m.agentId === noclick)));
    const linked = place.space ? null : (ownOpenChannels.find((c) => c.id === place.channel) ?? null);
    const space: WorkSpace =
        all.find((s) => s.id === place.space) ??
        (linked && all.find((s) => s.id === spaceIdOf(linked, spaces.personalId))) ??
        (place.channel ? null : all.find((s) => s.id === lastSpace())) ??
        (homeUsed ? null : spaces.spaces.find((s) => s.own)) ??
        home;
    // A channel the URL names that your lists don't hold yet (made since they were read): its space is known once
    // they're read again, so nothing is chosen (or remembered, or written) in its place before.
    const finding = !place.space && !linked && own.channels.findingOpen;
    const loaded = !spaces.loading && !own.channels.loading && !finding;
    // A first open (nothing remembered, nothing in the URL) that opens on the personal space lands on its new channel.
    const [firstOpen] = useState(() => !lastSpace() && !place.space && !place.channel);
    const openedOn = useRef(space.id);
    openedOn.current = space.id;
    const homePending = useHomeNoClickChannel(client, own.channels, loaded, home.name, noclick, readingAgents, (id) => {
        if (firstOpen && openedOn.current === HOME_SPACE) go({ space: HOME_SPACE, view: 'home', channel: id, thread: null }, { replace: true });
    });
    // Only a space chosen once the spaces are read is remembered: home stands in while they load.
    useEffect(() => {
        if (loaded) rememberSpace(space.id);
    }, [loaded, space.id]);

    // The space in the URL once it's known, so every view (and a copied link) reads the same one. A space named there
    // that's gone (left, deleted) takes what was open in it along.
    useEffect(() => {
        if (!loaded || place.space === space.id) return;
        go(place.space ? { space: space.id, channel: null, thread: null, agent: null, machine: false, panel: null, res: null, item: null } : { space: space.id }, { replace: true });
    }, [loaded, place.space, space.id, go]);

    // Which space opens takes both reads (your spaces, and whether your home has channels): drawn on one alone, Work
    // could open a space, read it, and switch away from it as the other lands.
    if (!loaded) return <WorkLoading />;
    if (own.channels.error && spaces.error) return <WorkNotice title="Work couldn't load" body={own.channels.error} action={{ label: 'Try again', onClick: () => (own.channels.refresh(), spaces.refresh()) }} />;

    const shared = { user, spaces, all, ownChannels: own.channels, homePending };
    return (
        <SpaceNoClicksContext.Provider value={spaceNoClicks}>
            {space.own ? <SpaceWork {...shared} space={space} client={client} transport={own.transport} channels={own.channels} /> : <JoinedSpace key={space.id} {...shared} space={space} />}
        </SpaceNoClicksContext.Provider>
    );
}

interface Shared {
    user: AccountMenuUser;
    spaces: Spaces;
    /** Every space on the rail. */
    all: WorkSpace[];
    /** Your own account's channels, for the rail's unread dots. */
    ownChannels: Channels;
    /** The personal space's channels aren't shown as they are yet: its NoClick channel may be on its way. */
    homePending: boolean;
}

/** A space you joined: its views read through a session acting as you there. */
function JoinedSpace(props: Shared & { space: WorkSpace }) {
    const [place] = useWorkPlace();
    const { client, error } = useSpaceClient(props.space);
    if (!client) return error ? <WorkNotice title={`Couldn't open ${props.space.name}`} body={error} /> : <WorkLoading />;
    return <JoinedChannels {...props} client={client} openId={openIdOf(place)} />;
}

function JoinedChannels(props: Shared & { space: WorkSpace; client: NoClick; openId: string | null }) {
    const { transport, channels } = useClientChannels(props.client, props.space, props.openId);
    // Everything the space reads, its own hooks included, goes as you there.
    return (
        <WorkClientContext.Provider value={props.client}>
            <SpaceWork {...props} transport={transport} channels={channels} />
        </WorkClientContext.Provider>
    );
}

function SpaceWork({ user, spaces, all, ownChannels, homePending, space, client, transport, channels }: Shared & { space: WorkSpace; client: NoClick; transport: PlatformTransport; channels: Channels }) {
    const [place, go] = useWorkPlace();
    const phone = useInPhoneShell();
    // On a laptop Agents' and DMs' list folds to its faces where what's open needs the room (measured on Work's own pane,
    // never the window), or where you folded it. Home and Resources keep their list at every width, and leave a fold you
    // chose for Agents and DMs to come back to.
    const [paneRef, pane] = useMeasuredWidth<HTMLDivElement>();
    const [foldedByChoice, setFoldedByChoice] = useFoldedByChoice();
    const folds = !place.machine && (place.view === 'agents' || place.view === 'dms');
    const { room, railed } = useListRoom(pane, LIST_COLUMN.useWidth(), folds, foldedByChoice);
    const person = !space.own && space.userId ? { me: space.userId, ownerName: space.accountName ?? 'The owner' } : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the client and whose eyes name the shelf
    const shelf = useMemo(() => platformShelf(client, person), [client, person?.me]);
    const drafts = useDrafts(transport);
    // Whose people the space has: a team space's, or your personal space's once you've shared it.
    const peopleId = space.workspaceId ?? space.sharedId ?? null;
    const people = useSpacePeople(peopleId);
    useSpaceNoClickJoins(client, space, channels.channels);
    const noclicks = useSpaceNoClicks();
    const viewer: WorkViewer = useMemo(
        () => ({ type: space.own ? 'account' : 'user', id: space.own ? null : (space.userId ?? null), name: user.display_name || user.email }),
        [space.own, space.userId, user.display_name, user.email]
    );

    const personalId = spaces.personalId;
    const placeOf = (c: Channel) => spaceIdOf(c, personalId);
    // A closed channel stays in Home, read-only; a closed DM goes.
    const open = useMemo(() => channels.channels.filter((c) => c.kind !== 'dm' || c.status !== 'closed'), [channels.channels]);
    const inSpace = useMemo(() => open.filter((c) => spaceIdOf(c, personalId) === space.id), [open, space.id, personalId]);
    const spaceChannels = useMemo(() => inSpace.filter((c) => c.kind !== 'dm').sort(byAge), [inSpace]);
    const dmChannels = useMemo(() => inSpace.filter((c) => c.kind === 'dm'), [inSpace]);
    const byName = useMemo(() => new Map(spaceChannels.map((c) => [c.name, c.id])), [spaceChannels]);
    const linked = open.find((c) => c.id === place.channel) ?? null;

    // What's open: the URL's, else (on a laptop) where you last were in the space, else its first.
    const fallback = phone ? null : place.view === 'home' ? openingChannel(spaceChannels, space.id) : place.view === 'dms' ? openingDm(dmChannels, space.id) : null;
    const channel = (linked && placeOf(linked) === space.id ? linked : null) ?? (place.channel ? null : fallback);
    // What each view has open is remembered for the space, once the URL names it, for the view to reopen (`showView`).
    useEffect(() => {
        if (place.space !== space.id) return;
        const open = spotOf(place, channel);
        if (open) rememberSpot(space.id, place.view, open);
    }, [place, channel, space.id]);
    const openedId = channel?.id;
    useEffect(() => {
        if (openedId) rememberOpened(openedId);
    }, [openedId]);
    // A link to the space's NoClick channel (Chat's news from the space) opens whichever channel that is, once the
    // channels and the space's NoClick are read.
    const noclick = useNoClickId();
    const spaceNoClick = useSpaceNoClick(space.workspaceId);
    const isTheNoClickChannel = (c: Channel) => isNoClickChannel(c, space.workspaceId ? null : noclick, spaceNoClick?.agentId);
    const itsNoClickChannel = place.channel === NOCLICK_HERE && !channels.loading && (space.workspaceId ? !!spaceNoClick : noclick !== undefined) ? (spaceChannels.find(isTheNoClickChannel) ?? spaceChannels.find((c) => c.name === EARLIER_NOCLICK_CHANNEL) ?? null) : undefined;
    useEffect(() => {
        if (itsNoClickChannel !== undefined) go({ view: 'home', channel: itsNoClickChannel?.id ?? null }, { replace: true });
    }, [itsNoClickChannel, go]);
    const questions = useSpaceQuestions(space.workspaceId);
    // A DM opened from Home (a link, the palette) lands in DMs, and a channel in Home.
    useEffect(() => {
        if (!linked) return;
        const view: WorkView = linked.kind === 'dm' ? 'dms' : 'home';
        if ((place.view === 'home' || place.view === 'dms') && place.view !== view) go({ view }, { replace: true });
    }, [linked, place.view, go]);
    // The channel a laptop opened by itself goes in the URL, so its history loads and a copied link names it.
    useEffect(() => {
        if (!place.channel && channel && !phone) go({ channel: channel.id }, { replace: true });
    }, [place.channel, channel, phone, go]);

    // An agent opens on its session: the one everyone talking to it shares, wherever they talk to it.
    const agentOpen = place.agent && place.agent !== NEW_AGENT ? place.agent : null;
    const sessions = useSessions(agentOpen);
    const session = sessions.sessions?.active ?? null;

    const followed = useFollowedThreads(shelf, space.workspaceId);
    const states = useAgentStates(space.workspaceId);

    // A row or tile the pointer rests on reads ahead what it opens: a channel's history; another of your spaces' Home
    // (its opening channel, its people, its threads and where its agents stand).
    const channelAhead = useIntent((id) => channels.prefetch(id));
    // The Resources tab: everything it shows of the space.
    const viewAhead = useIntent((view) => {
        if (view === 'resources') prefetchSpaceShare(client, space.id);
    });
    const spaceAhead = useIntent((id) => {
        const target = all.find((s) => s.id === id);
        if (!space.own || !target?.own || phone) return;
        const home = ownChannels.channels.filter((c) => c.status !== 'closed' && c.kind !== 'dm' && placeOf(c) === id).sort(byAge);
        const first = openingChannel(home, id);
        if (first) ownChannels.prefetch(first.id);
        if (!target.workspaceId) return;
        const workspaceId = target.workspaceId;
        prefetchV1(client, peopleKey(workspaceId), () => readPeople(client, workspaceId));
        prefetchV1(client, threadsKey(workspaceId), () => shelf.threads(workspaceId));
        prefetchV1(client, statesKey(workspaceId), () => readAgentStates(client, workspaceId));
    });
    // What waits on you in the Agents list: never on one of NoClick's helpers, which it doesn't list.
    const helpers = useHelperIds();
    const counts: ViewCounts = {
        agents: (states.data ?? []).reduce((n, s) => (helpers.has(s.agentId) ? n : n + s.waiting.total), 0),
        dms: dmChannels.reduce((n, c) => n + c.unread, 0),
    };

    // The palette can open any channel, DM, agent or space by name.
    const agents = useAgents();
    const remember = useWork().palette?.remember;
    useEffect(() => {
        if (!remember) return;
        const home = (c: Channel) => ({ view: c.kind === 'dm' ? ('dms' as const) : ('home' as const), space: spaceIdOf(c, personalId), channel: c.id, thread: null, agent: null, panel: null, machine: false });
        remember([
            ...open.map((c) =>
                c.kind === 'dm'
                    ? { id: `dm:${c.id}`, label: otherIn(c)?.name ?? c.name, context: `DM in ${space.name}`, icon: MessagesSquare, run: () => go(home(c)) }
                    : { id: `channel:${c.id}`, label: c.name, context: all.find((s) => s.id === spaceIdOf(c, personalId))?.name, icon: Hash, about: c.topic, run: () => go(home(c)) }
            ),
            ...(agents.data ?? []).filter((a) => !isSpaceNoClick(a) && !a.helper).map((a) => ({ id: `agent:${a.id}`, label: nameOf(a, noclicks), context: 'Agent', icon: UsersRound, run: () => go({ view: 'agents', agent: a.id, machine: false, thread: null, panel: null }) })),
            ...all.map((s) => ({ id: `space:${s.id}`, label: s.name, context: 'Space', icon: BriefcaseBusiness, run: () => go({ space: s.id, view: 'home', channel: null, thread: null, agent: null, panel: null, machine: false }) })),
        ]);
    }, [remember, open, all, agents.data, space.name, go, noclicks, personalId]);

    // A key can't open the personal space to people: only its owner, signed in, can (screens/console/ownerOnly.ts).
    const sharesPersonal = useOwnerOnly()('sharePersonalSpace');
    const [makingSpace, setMakingSpace] = useState(false);
    const [editingSpace, setEditingSpace] = useState(false);
    const [startingChannel, setStartingChannel] = useState(false);
    const channelPicks = usePickerAgents(channels.agents, startingChannel, space.workspaceId);
    const [inviting, setInviting] = useState(false);

    const startDm = async (userId: string) => {
        if (!peopleId) return;
        try {
            const dm = await PlatformChannel.dm(userId, { workspace: peopleId, client, user: null });
            channels.refresh();
            go({ view: 'dms', channel: dm.id, thread: null, machine: false, panel: null });
        } catch (e) {
            toast.error(errorText(e));
        }
    };

    const nav: WorkNav = useMemo(
        () => ({
            openChannel: (id, options = {}) => {
                const target = open.find((c) => c.id === id);
                go(
                    { view: target?.kind === 'dm' ? 'dms' : 'home', space: target ? spaceIdOf(target, personalId) : null, channel: id, thread: options.thread ?? null, machine: false, subagent: null, agent: null, panel: place.panel === 'profile' ? null : undefined },
                    { replace: options.replace }
                );
            },
            openDm: (userId) => {
                const dm = dmChannels.find((c) => c.members.some((m) => m.kind === 'human' && (m.id === userId || m.userId === userId)));
                if (dm) go({ view: 'dms', channel: dm.id, thread: null, machine: false });
                else void startDm(userId);
            },
            openAgent: (agentId) => {
                prefetchConversation(client, agentId);
                go({ view: 'agents', agent: agentId, machine: false, subagent: null, thread: null, panel: place.panel === 'profile' ? null : undefined });
            },
            openProfile: (agentId, at) => go({ agent: agentId, panel: 'profile', thread: null, profileTab: at?.tab ?? null, trigger: at?.trigger ?? null }),
            // The machine page opens in the main pane's place, in whichever view asked (an agent's session, Resources).
            openMachine: (agentId) => go({ agent: agentId, machine: true, thread: null }),
            newAgent: () => go({ view: 'agents', agent: NEW_AGENT, machine: false }),
            openHome: () => go({ view: 'home', channel: null, thread: null, agent: null, machine: false, subagent: null, panel: null }),
            openMembers: (tab = 'people') => go({ panel: tab, thread: null }),
            closePanel: () => go({ panel: null, thread: null, profileTab: null, trigger: null }),
            subagent: place.subagent,
            openSubagent: (id, options) => go({ subagent: id }, { replace: options?.replace }),
        }),
        // eslint-disable-next-line react-hooks/exhaustive-deps -- startDm reads the space it was made for
        [open, dmChannels, go, place.panel, place.subagent, space.id, client, personalId]
    );

    // A space made here opens on its NoClick channel. If that fails the space stays as it is, and the error offers to try again.
    const startNoClickChannel = async (made: WorkSpace) => {
        try {
            const opened = await openNoClickChannel(client, made.workspaceId!);
            channels.refresh();
            go({ space: made.id, view: 'home', channel: opened.id, thread: null, agent: null, machine: false, panel: null });
        } catch (e) {
            toast.error(`Couldn’t start #${NOCLICK_CHANNEL} in ${made.name}`, { description: errorText(e), duration: Infinity, action: { label: 'Try again', onClick: () => void startNoClickChannel(made) } });
        }
    };
    // Inviting people to your personal space shares it first (its workspace, made once), then asks as a team space does.
    const invite = async () => {
        if (space.workspaceId || space.sharedId) return setInviting(true);
        if (!sharesPersonal) return toast(ownerOnlyWhy('sharePersonalSpace'));
        try {
            const id = await spaces.sharePersonal();
            await prefetchV1(client, peopleKey(id), () => readPeople(client, id));
            setInviting(true);
        } catch (e) {
            toast.error('Couldn’t share your personal space', { description: errorText(e) });
        }
    };
    const switchSpace = (id: string) => go({ space: id, channel: null, thread: null, agent: null, machine: false, panel: null, res: null, item: null });
    // What a laptop reopens in a view: what was last open in it in this space, where that's still here. A channel you
    // left, a DM that closed or an agent deleted since opens the view as it opens without it; a resource gone since
    // says so on its page.
    const reopened = (view: WorkView): Spot => {
        const spot = phone ? null : lastSpot(space.id, view);
        if (!spot) return {};
        if (view === 'home') return spot.channel === THREADS || spaceChannels.some((c) => c.id === spot.channel) ? spot : {};
        if (view === 'dms') return dmChannels.some((c) => c.id === spot.channel) ? spot : {};
        if (view === 'resources') return spot;
        const pinned = space.workspaceId ? spaceNoClick?.agentId : noclick;
        return spot.agent && (spot.agent === pinned || states.data?.some((s) => s.agentId === spot.agent)) ? spot : {};
    };
    // Each view reopens its own (a phone shows its list); Agents keeps an agent the URL already names, one whose
    // profile is beside.
    const showView = (view: WorkView) => {
        const keeps = view === 'agents' && !!place.agent;
        const spot = keeps ? {} : reopened(view);
        go({
            view,
            channel: spot.channel ?? null,
            thread: spot.thread ?? null,
            machine: false,
            ...(keeps ? {} : { agent: spot.agent ?? null }),
            panel: spot.profile ? 'profile' : place.panel === 'profile' ? null : undefined,
            res: spot.res ?? null,
            item: spot.item ?? null,
        });
    };
    const back = () => go({ channel: null, thread: null, agent: null, machine: false, panel: null });
    const memberAction = (m: ChannelMember) => {
        if (m.kind === 'agent' && m.agentId) nav.openProfile(m.agentId);
        else if (m.kind === 'human') nav.openDm(m.userId ?? m.id);
    };
    const meIn = (author: Pick<ChannelAuthor, 'type' | 'id'>) => author.type === 'account' && !author.id;
    const authorName = (author: ChannelAuthor) => (meIn(author) ? 'You' : (authorMember(author, channel?.members ?? []) ?? { name: author.name }).name);
    const manages = space.role === 'owner' || space.role === 'admin';
    // A template is added by the account to a space of its own (only the owner adds): its Home lists the gallery, and
    // an add from there aims at it (your personal space, at a new space).
    const addsTemplates = space.own && !space.archived;
    const templateInto = space.id === HOME_SPACE ? null : space.workspaceId;
    const [spaceAsk, setSpaceAsk] = useState<SpaceAsk | null>(null);
    const [savingTemplate, setSavingTemplate] = useState(false);

    // ── the view's list ─────────────────────────────────────────────────────
    const dmRows: DmRow[] = dmChannels.flatMap((c) => {
        const other = otherIn(c);
        return other ? [{ channel: c, person: other }] : [];
    });
    const inDm = new Set(dmRows.map((d) => d.person.userId ?? d.person.id));
    const others = people.people.filter((p) => p.userId && p.userId !== space.userId);
    const strangers: ChannelMember[] = others.filter((p) => !inDm.has(p.userId!)).map((p) => ({ id: p.userId!, userId: p.userId!, kind: 'human', name: p.name ?? p.email ?? 'Someone' }));
    // Who a new channel can take besides its agents: the space's people, each with when they were last on.
    const channelPeople: PersonChoice[] = others.map((p) => ({ id: p.userId!, name: p.name ?? p.email ?? 'Someone', detail: presenceOf(p.lastSeenAt) ?? p.email }));
    // Home waits, never drawn empty, until its channels are read and (the personal space's) its NoClick channel is in.
    const homeLoading = channels.loading || (space.id === HOME_SPACE && homePending);
    const newChannel = space.role === 'guest' || space.archived ? null : () => setStartingChannel(true);
    const inviteMore = manages && !space.archived && (space.workspaceId || space.sharedId || sharesPersonal) ? () => void invite() : null;
    const online = (p: ChannelMember) => presenceOf(people.people.find((m) => m.userId === (p.userId ?? p.id))?.lastSeenAt ?? null) === 'Online';
    const viewList =
        place.view === 'home' ? (
            <HomeList
                channels={spaceChannels}
                workspaceId={space.workspaceId}
                loading={homeLoading}
                openId={place.channel === THREADS || place.channel === TEMPLATES ? place.channel : (channel?.id ?? null)}
                threads={followed.threads ? followed.unread : 0}
                templates={addsTemplates}
                onOpen={(id) => go({ channel: id, thread: null })}
                ahead={channelAhead}
                onNewChannel={newChannel}
                onStar={(id, on) => channels.setPreference(id, 'starred', on)}
            />
        ) : place.view === 'dms' ? (
            <DmsList
                dms={dmRows}
                others={strangers}
                openId={channel?.id ?? null}
                user={user}
                myName={meIn}
                online={online}
                onOpen={(id) => go({ channel: id, thread: null })}
                ahead={channelAhead}
                onStart={(p) => void startDm(p.userId ?? p.id)}
                onInvite={inviteMore}
                emailOf={(p) => people.people.find((m) => m.userId === (p.userId ?? p.id))?.email ?? null}
            />
        ) : place.view === 'agents' ? (
            <AgentsList spaceId={space.workspaceId} selectedAgentId={place.agent} onOpen={(id) => nav.openAgent(id)} onNew={nav.newAgent} />
        ) : place.view === 'resources' ? (
            <SpaceResourcesNav spaceId={space.id} />
        ) : null;
    // An archived space says so atop whichever list it shows.
    const list = (
        <>
            {space.archived && <ArchivedBanner />}
            {viewList}
        </>
    );

    // ── what's open ─────────────────────────────────────────────────────────
    const dmOther = channel?.kind === 'dm' ? otherIn(channel) : null;
    const dmPerson = dmOther ? (people.people.find((p) => p.userId === (dmOther.userId ?? dmOther.id)) ?? null) : null;
    const main = place.template ? (
        <AddTemplatePage
            source={place.template}
            target={place.into}
            spaces={spaces.spaces}
            onTarget={(id) => go({ into: id }, { replace: true })}
            // Its space is opened once your spaces are read again with it, or Work would open another in its place.
            onAdded={(added) =>
                void spaces.refresh().then(() =>
                    go({ template: null, into: null, space: added.workspaceId, view: 'home', channel: added.channelId, thread: null, agent: null, machine: false, panel: null })
                )
            }
        />
    ) : place.machine && agentOpen ? (
            <MachinePage agentId={agentOpen} file={place.file} onFile={(file) => go({ file }, { replace: true })} onBack={() => go({ machine: false })} />
        ) : place.view === 'resources' ? (
            // Home's (`space.id` is HOME_SPACE) are its agents in no space and what the account has for them.
            <SpaceResourcesPane spaceId={space.id} />
        ) : place.view === 'agents' ? (
            place.agent === NEW_AGENT ? (
                <NewAgent spaceId={space.workspaceId} onCreated={(agentId) => nav.openAgent(agentId)} onCancel={() => go({ agent: null }, { replace: true })} />
            ) : agentOpen && session ? (
                <AgentConversation key={`${agentOpen}:${session}`} agentId={agentOpen} conversation={session} onOpenProfile={() => nav.openProfile(agentOpen)} onOpenMachine={() => nav.openMachine(agentOpen)} />
            ) : agentOpen && sessions.error ? (
                <WorkNotice title="Couldn’t open its session" body={errorText(sessions.error)} action={{ label: 'Try again', onClick: () => void sessions.refresh() }} />
            ) : agentOpen ? (
                // Its screen at once while Work reads which session it's in (the conversation then takes its place).
                <AgentOpening agentId={agentOpen} />
            ) : place.agent ? null : (
                <AgentsEmpty spaceId={space.workspaceId} onOpen={(id) => nav.openAgent(id)} onNew={nav.newAgent} />
            )
        ) : place.view === 'home' && place.channel === TEMPLATES && addsTemplates ? (
            <TemplatesPane
                listing={place.listing}
                spaceName={space.name}
                into={templateInto}
                phone={phone}
                onBack={back}
                onOpen={(slug) => go({ listing: slug })}
                onAdd={(address) => go({ template: address, into: templateInto })}
            />
        ) : place.view === 'home' && place.channel === THREADS ? (
            <ThreadsPane followed={followed} nameOf={authorName} phone={phone} onBack={back} onOpen={(channelId, parentId) => nav.openChannel(channelId, { thread: parentId })} />
        ) : channel ? (
            <ChannelPane
                channel={channel}
                channels={channels}
                transport={transport}
                shelf={shelf}
                drafts={drafts}
                user={user}
                spaceName={space.name}
                byName={byName}
                dmWith={channel.kind === 'dm' ? otherIn(channel) : null}
                dmPresence={dmPerson ? presenceOf(dmPerson.lastSeenAt) : null}
                dmAbout={dmPerson ? [roleLabel(dmPerson.role), dmPerson.email].filter(Boolean).join(' · ') : null}
                phone={phone}
                onBack={back}
                onOpenChannel={(id) => nav.openChannel(id)}
                onThread={(messageId) => go({ thread: messageId, panel: null })}
                onMember={memberAction}
                onGone={() => go({ channel: null, thread: null }, { replace: true })}
                manages={manages}
                archived={space.archived}
                onUnarchive={space.own && space.archived ? () => void unarchiveSpace(spaces, space) : undefined}
                asked={isTheNoClickChannel(channel) && questions?.length ? { count: questions.length, onOpen: () => nav.openMembers('questions') } : undefined}
            />
        ) : place.view === 'home' ? (
            // Nothing open while a channel the URL names is still being found.
            homeLoading || channels.findingOpen || place.channel === NOCLICK_HERE ? null : spaceChannels.length ? (
                <HomeEmpty channels={spaceChannels} spaceName={space.name} onOpen={(id) => go({ channel: id, thread: null })} onNewChannel={newChannel} />
            ) : channels.error && !channels.channels.length ? (
                <WorkNotice title="Couldn’t read your channels" body={channels.error} action={{ label: 'Try again', onClick: () => channels.refresh() }} />
            ) : (
                <WorkNotice
                    title={`Nothing in ${space.name} yet`}
                    body={space.role === 'guest' ? 'Nobody has added you to a channel here yet.' : 'Start a channel and add your agents to it.'}
                    action={space.role === 'guest' ? undefined : { label: 'Start a channel', onClick: () => setStartingChannel(true) }}
                />
            )
        ) : place.view === 'dms' ? (
            channels.loading || channels.findingOpen || (!dmRows.length && people.loading) ? null : (
                <DmsEmpty
                    dms={dmRows}
                    others={strangers}
                    user={user}
                    spaceName={space.id === HOME_SPACE ? 'your personal space' : space.name}
                    myName={meIn}
                    online={online}
                    onOpen={(id) => go({ channel: id, thread: null })}
                    onStart={(p) => void startDm(p.userId ?? p.id)}
                    onInvite={inviteMore}
                />
            )
        ) : null;

    // ── beside it ───────────────────────────────────────────────────────────
    const panel =
        place.thread && channel ? (
            <ThreadPanel
                key={place.thread}
                channel={channel}
                parentId={place.thread}
                parent={channels.history(channel.id)?.messages.find((m) => m.id === place.thread)}
                transport={transport}
                shelf={shelf}
                drafts={drafts}
                members={channel.members}
                user={user}
                byName={byName}
                phone={phone}
                onOpenChannel={(id) => nav.openChannel(id)}
                onClose={() => go({ thread: null })}
            />
        ) : place.panel === 'profile' && place.agent && place.agent !== NEW_AGENT ? (
            <PanelFrame phone={phone}>
                <AgentProfile
                    key={place.agent}
                    agentId={place.agent}
                    onClose={() => go({ panel: null, profileTab: null, trigger: null })}
                    onOpenMachine={() => nav.openMachine(place.agent!)}
                    onOpenChannel={(id) => nav.openChannel(id)}
                />
            </PanelFrame>
        ) : place.panel === 'questions' && space.workspaceId ? (
            questions?.length ? <SpaceQuestionsPanel questions={questions} spaceName={space.name} phone={phone} onClose={() => go({ panel: null })} /> : null
        ) : place.panel && place.panel !== 'profile' && peopleId ? (
            <MembersPanel
                space={space}
                people={people}
                tab={place.panel}
                user={user}
                agents={channels.agents}
                phone={phone}
                onTab={(tab) => go({ panel: tab }, { replace: true })}
                onClose={() => go({ panel: null })}
                onInvite={() => setInviting(true)}
                onAgent={(agentId) => nav.openProfile(agentId)}
                onPerson={(p) => p.userId && nav.openDm(p.userId)}
            />
        ) : null;

    const dialogs = (
        <>
            <SpaceDialog
                open={makingSpace}
                onOpenChange={setMakingSpace}
                onSave={async (name, logo) => {
                    const made = await spaces.create(name, logo);
                    switchSpace(made.id);
                    await startNoClickChannel(made);
                }}
            />
            <SpaceDialog open={editingSpace} onOpenChange={setEditingSpace} space={space} onSave={(name, logo) => spaces.update(space, name, logo, client)} />
            <NewChannelDialog
                open={startingChannel}
                onOpenChange={setStartingChannel}
                where={space.name}
                agents={channelPicks}
                people={channelPeople}
                agentsHref="/dashboard?tab=work&show=agents"
                user={user}
                onCreate={async (input) => {
                    const made = await channels.createChannel({ ...input, workspaceId: space.workspaceId });
                    go({ view: 'home', channel: made.id, thread: null });
                }}
            />
            {peopleId && <InviteDialog open={inviting} onOpenChange={setInviting} space={space} people={people} />}
            {spaceAsk && <SpaceSettingsDialog ask={spaceAsk} space={space} spaces={spaces} onClose={() => setSpaceAsk(null)} />}
            {savingTemplate && <SaveTemplateDialog space={space} client={client} onClose={() => setSavingTemplate(false)} />}
        </>
    );
    const headerWith = (end: ReactNode) => (
        <SpaceHeader
            space={space}
            spaces={phone ? all : undefined}
            onSpace={switchSpace}
            people={peopleId && !people.loading ? people.people.length + (space.own ? 1 : 0) : null}
            agents={space.workspaceId && !space.personal && !people.loading ? people.agents.length : null}
            onInvite={() => void invite()}
            onMembers={(tab) => nav.openMembers(tab)}
            onEdit={() => setEditingSpace(true)}
            onNewSpace={() => setMakingSpace(true)}
            asked={questions?.length ?? 0}
            onAsk={setSpaceAsk}
            onUnarchive={() => void unarchiveSpace(spaces, space)}
            onSaveTemplate={() => setSavingTemplate(true)}
            end={end}
        />
    );
    const header = headerWith(null);

    // The views below read and write as you in this space (your own client, or your session in one you joined).
    const scoped = (children: ReactNode) => (
        <WorkClientContext.Provider value={client}>
            <WorkViewerContext.Provider value={viewer}>
                <WorkNavContext.Provider value={nav}>
                    <AgentRoles>
                        <TooltipProvider delayDuration={250}>{children}</TooltipProvider>
                    </AgentRoles>
                </WorkNavContext.Provider>
            </WorkViewerContext.Provider>
        </WorkClientContext.Provider>
    );

    if (phone) {
        // A phone shows the list, or one thing open over it.
        const screen = panel ?? (place.template || place.machine || (place.view === 'resources' ? place.res : place.channel || place.agent) ? main : null);
        // The bar's way back over what doesn't draw its own (a channel, a thread and the machine page do).
        const shownAgent = (agents.data ?? []).find((a) => a.id === place.agent);
        const agentName = shownAgent ? nameOf(shownAgent, noclicks) : 'Agent';
        const phoneBack = !screen ? null : place.template && !panel ? (
            <PhoneBarBack label="Back" onBack={() => go({ template: null, into: null })} />
        ) : place.thread || place.machine || (place.subagent && !panel) || (!panel && place.view !== 'agents' && place.view !== 'resources') ? null : panel ? (
            <PhoneBarBack label="Back" title={<span className="truncate">{place.panel === 'profile' ? agentName : place.panel === 'questions' ? ASKED_TITLE : `Members of ${space.name}`}</span>} onBack={() => go({ panel: null })} />
        ) : place.view === 'resources' ? (
            <PhoneBarBack label={place.item && isSpaceKind(place.res) ? kindOf(place.res).label : 'Resources'} onBack={() => go(place.item ? { item: null } : { res: null })} />
        ) : (
            <PhoneBarBack label="Agents" title={<span className="truncate">{place.agent === NEW_AGENT ? 'New agent' : agentName}</span>} onBack={back} />
        );
        return scoped(
            <>
                <div className="flex h-full min-h-0 flex-col" data-testid="work-page">
                    {phoneBack}
                    {screen ? (
                        <div className="flex min-h-0 flex-1 flex-col">{screen}</div>
                    ) : (
                        <>
                            {/* Above the list as on a laptop, so the space's mark lines up with the search and the rows'
                                faces under it, and stays while the list scrolls. */}
                            {header}
                            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-6 scrollbar-subtle">{list}</div>
                            <ViewBar view={place.view} counts={counts} onView={showView} />
                        </>
                    )}
                </div>
                {dialogs}
            </>
        );
    }

    const ownUnread = (s: WorkSpace) => (s.own ? ownChannels.channels : channels.channels).some((c) => placeOf(c) === s.id && c.unread > 0);
    const noun = place.view === 'dms' ? 'people' : 'agents';
    return scoped(
        <>
            <div className="flex h-full min-h-0" data-testid="work-page">
                <SpaceRail spaces={all} current={space.id} unread={ownUnread} onSpace={switchSpace} onNew={() => setMakingSpace(true)} ahead={spaceAhead} />
                <ViewRail view={place.view} counts={counts} onView={showView} ahead={viewAhead} />
                <div className="flex min-w-0 flex-1">
                    <ListColumn
                        rail={folds}
                        docked={!railed}
                        head={headerWith}
                        showLabel={`Show ${noun}`}
                        hideLabel={`Hide ${noun}`}
                        // Folded by choice where there's room: showing it docks it again, clearing the choice.
                        onShow={foldedByChoice && room ? () => setFoldedByChoice(false) : undefined}
                        onFold={() => setFoldedByChoice(true)}
                    >
                        {list}
                    </ListColumn>
                    <div ref={paneRef} className="flex min-w-0 flex-1 flex-col">
                        {main}
                    </div>
                    {panel}
                </div>
            </div>
            {dialogs}
        </>
    );
}
