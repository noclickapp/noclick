// Each of the account's spaces has a NoClick of its own (`GET /v1/workspaces/{id}/noclick`, made on first ask, a
// member of the space), and a space Work makes opens on its NoClick channel: that NoClick in it, answering every
// message, the place to change the space by messaging NoClick. Made through the SDK right after the space itself, by
// Work's own create flow alone: a workspace a developer's code makes for its users (the API's workspace create) gets
// none. The personal space (the account's channels in no workspace) has the account's own NoClick in its NoClick
// channel, made the first time Work finds none there: its owner's alone, never shown to the people they share it with.
import { useMemo } from 'react';
import { Channel, Conflict, NO_USER, type NoClick } from 'noclick';
import type { Channel as Room } from '@/screens/channels/types';
import type { Channels } from '@/screens/channels/useChannels';
import { noclickNaming, useSpaceNoClicks, useWorkV1, YOUR_NOCLICK, type SpaceNoClick, type SpaceNoClicks } from './agents/reads';
import type { WorkSpace } from './spaces';

/** The NoClick channel's name: changing it here renames it everywhere Work makes or finds one. */
export const NOCLICK_CHANNEL = 'noclick';
export const NOCLICK_CHANNEL_TOPIC = 'Tell NoClick what to change in this space: channels, agents, people.';
/** The personal space's: the account's own NoClick answers there. */
export const HOME_NOCLICK_CHANNEL_TOPIC = `${noclickNaming(null).line}. Tell it what you need.`;

/** The topic a NoClick channel shows: one Work wrote says whose NoClick answers there (a personal space's made with the
 *  space's topic says yours); one someone set stays theirs. */
export const noclickChannelTopic = (channel: Pick<Room, 'workspaceId' | 'topic'>) =>
    !channel.workspaceId && channel.topic === NOCLICK_CHANNEL_TOPIC ? HOME_NOCLICK_CHANNEL_TOPIC : channel.topic;

/** What the NoClick channel was called before: a space made then still holds it. */
export const EARLIER_NOCLICK_CHANNEL = 'intro';

/** Whether `channel` is a space's NoClick channel: its name, with a NoClick in it (the space's own, `spaceNoClickId`,
 *  known by the platform's flag until it's read; in the personal space the account's, `noclickId`). */
export const isNoClickChannel = (channel: Room, noclickId: string | null | undefined, spaceNoClickId?: string) =>
    channel.kind !== 'dm' &&
    channel.name === NOCLICK_CHANNEL &&
    channel.members.some((m) => (!!noclickId && m.agentId === noclickId) || (spaceNoClickId ? m.agentId === spaceNoClickId : !!m.noclick));

/** Each space's NoClick's agent id, asked once a session per client (made by the first ask; a failure is asked again).
 *  Work names it itself (`noclickNaming`), from the space's name as it reads it now. */
const spaceNoClicks = new WeakMap<NoClick, Map<string, Promise<string>>>();
export function spaceNoClickId(client: NoClick, workspaceId: string): Promise<string> {
    const held = spaceNoClicks.get(client) ?? new Map<string, Promise<string>>();
    spaceNoClicks.set(client, held);
    const was = held.get(workspaceId);
    if (was) return was;
    const asking = client.request<{ agent_id: string }>('GET', `/v1/workspaces/${encodeURIComponent(workspaceId)}/noclick`, { user: null }).then((raw) => raw.agent_id);
    held.set(workspaceId, asking);
    asking.catch(() => held.delete(workspaceId));
    return asking;
}

/** The NoClicks of `spaces` that are the account's own, each asked for once a session (which makes it): read by Work
 *  for every view (`SpaceNoClicksContext`), so each is named for its space. */
export function useOwnSpaceNoClicks(spaces: readonly WorkSpace[]): SpaceNoClicks {
    const own = spaces.flatMap((s) => (s.own && s.workspaceId ? [s.workspaceId] : [])).sort();
    const read = useWorkV1(own.length ? `work:space-noclicks:${own.join(',')}` : null, async (client) => {
        const got = await Promise.allSettled(own.map((id) => spaceNoClickId(client, id)));
        return own.flatMap((id, i) => {
            const one = got[i];
            if (one.status === 'rejected') console.warn(`[work] couldn't read the NoClick of the space ${id}:`, one.reason);
            return one.status === 'fulfilled' ? [[id, one.value] as const] : [];
        });
    });
    // Named again when a space is renamed.
    const named = JSON.stringify(spaces.flatMap((s) => (s.workspaceId ? [[s.workspaceId, s.name]] : [])));
    const personal = spaces.flatMap((s) => (s.personal && s.workspaceId ? [s.workspaceId] : [])).join(',');
    return useMemo(() => {
        const names = new Map<string, string>(JSON.parse(named) as [string, string][]);
        const of = new Map<string, SpaceNoClick>((read.data ?? []).map(([id, agentId]) => [id, { agentId, ...noclickNaming({ name: names.get(id) }) }]));
        return { of, names, personal: new Set(personal.split(',').filter(Boolean)) };
    }, [read.data, named, personal]);
}

/** The NoClick of the space `workspaceId`: one of the account's own as Work read it, else (a space you joined) asked
 *  for here while `reading`; none for a personal space, yours or one you joined. */
export function useSpaceNoClick(workspaceId: string | null, reading = true): SpaceNoClick | undefined {
    const spaces = useSpaceNoClicks();
    const own = spaces.of.get(workspaceId ?? '');
    const asks = reading && !!workspaceId && !own && !spaces.personal.has(workspaceId);
    const read = useWorkV1(asks ? `work:space-noclick:${workspaceId}` : null, (client) => spaceNoClickId(client, workspaceId!));
    const name = spaces.names.get(workspaceId ?? '');
    const joined = read.data;
    return useMemo(() => own ?? (joined ? { agentId: joined, ...noclickNaming({ name }) } : undefined), [own, joined, name]);
}

/** What a space's channels from before each space had its own NoClick need (the account's NoClick is silent in them):
 *  the space's NoClick in its #noclick or #intro holding the account's (`add`), then the account's taken out of any
 *  channel holding both (`drop`, its member). */
export function spaceNoClickFixes(channels: readonly Room[], workspaceId: string, noclickId: string, spaceNoClickId: string) {
    const theirs = channels.filter((c) => c.kind !== 'dm' && c.status !== 'closed' && c.workspaceId === workspaceId && c.members.some((m) => m.agentId === noclickId));
    const holds = (c: Room) => c.members.some((m) => m.agentId === spaceNoClickId);
    return {
        add: theirs.filter((c) => !holds(c) && (c.name === NOCLICK_CHANNEL || c.name === EARLIER_NOCLICK_CHANNEL)).map((c) => c.id),
        drop: theirs.filter(holds).map((c) => ({ channel: c.id, member: c.members.find((m) => m.agentId === noclickId)!.id })),
    };
}

/** What was done to each channel this session, per client: each change is made once, whatever the answer. */
const fixed = new WeakMap<NoClick, Set<string>>();
const once = (client: NoClick, key: string) => {
    const seen = fixed.get(client) ?? new Set<string>();
    fixed.set(client, seen);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
};

/** Adds the space's NoClick (`agentId`) to `channelId`, once a session (a 409: it's there already). */
export async function giveSpaceNoClick(client: NoClick, channelId: string, agentId: string): Promise<void> {
    if (!once(client, `add:${channelId}`)) return;
    try {
        await Channel.fromId(channelId, { client, user: null }).add({ agentId });
    } catch (e) {
        if (!(e instanceof Conflict)) throw e;
    }
}

/** Takes the account's NoClick (its member `memberId`) out of `channelId`, once a session. */
export async function dropAccountNoClick(client: NoClick, channelId: string, memberId: string): Promise<void> {
    if (!once(client, `drop:${channelId}`)) return;
    await Channel.fromId(channelId, { client, user: null }).remove(memberId);
}

/** Whether the personal space's channels (the account's in no workspace) hold one with NoClick's own agent in it,
 *  whatever it's called. */
export const homeHoldsNoClick = (channels: readonly Room[], noclickId: string) =>
    channels.some((c) => c.kind !== 'dm' && !c.workspaceId && c.members.some((m) => m.agentId === noclickId));

/** Opens the NoClick channel in the space `workspaceId` with the space's own NoClick in it (already a member of the
 *  space), answering every message. Run again after a failure, it takes what's already there. */
export async function openNoClickChannel(client: NoClick, workspaceId: string): Promise<Channel> {
    const noclick = await spaceNoClickId(client, workspaceId);
    return await Channel.create(NOCLICK_CHANNEL, { client, workspace: workspaceId, members: [{ agentId: noclick }], topic: NOCLICK_CHANNEL_TOPIC, mode: 'all', allowExisting: true });
}

/** The personal space's NoClick channel as made (or found) this session, per client. */
const homeMade = new WeakMap<NoClick, Promise<Room | null>>();

/** Makes the personal space's NoClick channel with NoClick's own agent (`noclickId`, as Work read it) in it, once a
 *  session: none if the account already has a channel in no workspace with NoClick in it, read afresh, open or closed
 *  (outside a workspace a name isn't unique, so it's never found by name). Made through `create`, the page's channels,
 *  which list it the moment it's made. Answers the channel it made, else null; a failure is tried again by the next
 *  caller. */
export function makeHomeNoClickChannel(client: NoClick, noclickId: string, create: Channels['createChannel']): Promise<Room | null> {
    const held = homeMade.get(client);
    if (held) return held;
    const making = (async () => {
        const holding = await Channel.list({ client, userFilter: NO_USER, agent: noclickId, kind: 'channel' });
        if (holding.some((c) => !c.workspaceId)) return null;
        return await create({ workspaceId: null, name: NOCLICK_CHANNEL, topic: HOME_NOCLICK_CHANNEL_TOPIC, agents: [{ id: noclickId, source: 'platform', name: YOUR_NOCLICK, noclick: true }] });
    })();
    homeMade.set(client, making);
    making.catch(() => homeMade.delete(client));
    return making;
}
