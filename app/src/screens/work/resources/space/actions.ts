// What each change to a space's resources does: an agent joins or leaves the space; anything else is shared with its
// people or taken back (agents that hold it as their own keep it); a level changes what its people get; a delete is
// account-wide, to the trash, after the platform's own preview. A connection or a secret is removed for good instead:
// its access ends everywhere (a secret comes off each agent that holds it first). Each says what happened and offers
// it back where it can come back.
import { toast } from 'sonner';
import { errorText } from '@/screens/console/pages/resources/shared';
import { invalidateV1 } from '@/sdk/useV1';
import { Agent, Channel, TrashItem, Workspace, type NoClick } from 'noclick';
import { renameKnowledge } from '@/screens/resources/knowledge';
import { removeSecret, SECRETS_KEY } from '@/screens/resources/secrets';
import { AGENTS_KEY } from '../../agents/reads';
import { MEMORIES_KEY, SKILLS_KEY } from '../knowledge/store';
import { OWN_KEY } from '../machines';
import { CONNECTIONS_KEY, LINK_KIND, readSpaceAgain, setLevels, share, SPACES_KEY, unshare, type SpaceLink, type Thing } from './data';

const list = (names: string[]) => new Intl.ListFormat('en', { type: 'conjunction' }).format(names);
const failed = (what: string, error: unknown) => toast.error(what, { description: errorText(error) });
export const titleFor = (t: Pick<Thing, 'kind' | 'name'>) => (t.kind === 'channels' ? `#${t.name}` : t.name);

const space = (client: NoClick, spaceId: string) => Workspace.fromId(spaceId, { client, user: null });

/** Can be taken out of the space on its own: an agent (it leaves), or anything shared with it. */
export const removable = (t: Thing) => t.kind === 'agents' || !!t.link;
/** Renamed here: a named skill or memory, or a channel. */
export const renamable = (t: Thing) => t.kind === 'channels' || ((t.kind === 'skills' || t.kind === 'memories') && !!t.knowledge?.name);
/** Removed for good, its access ending everywhere: a connection (its credential revoked) or a secret. */
export const removedForGood = (t: Thing) => t.kind === 'connections' || t.kind === 'secrets';
/** One of the account's machines (a machine kept on, or a computer of yours), never an agent's sandbox. */
const aMachine = (t: Thing) => (t.place ? t.place.kind === 'machine' || t.place.kind === 'own' : t.machine?.kind === 'machine');
/** A kind a space shares, and of a machine's rows the machines themselves. */
const linkable = (t: Thing) => !!LINK_KIND[t.kind] && (t.kind !== 'machines' || aMachine(t));
/** Shared with the space here: a kind a space shares that isn't yet. */
export const shareable = (t: Thing) => linkable(t) && !t.link;
/** Given to a space from home: an agent joins one, a kind a space shares is shared with it. */
export const givable = (t: Thing) => t.kind === 'agents' || linkable(t);

/** Where its delete goes, or null where it isn't deleted from here (a sandbox, a machine kept on, a number, an address). */
export function deletePath(t: Thing): string | null {
    switch (t.kind) {
        case 'agents':
            return `/v1/agents/${t.ref}`;
        case 'skills':
            return `/v1/skills/${t.ref}`;
        case 'memories':
            return t.knowledge?.kind === 'memory' && t.knowledge.agentId ? null : `/v1/memories/${t.ref}`;
        case 'connections':
            return `/v1/connections/${encodeURIComponent(t.ref)}`;
        case 'secrets':
            return `/v1/secrets/${t.ref}`;
        case 'channels':
            return `/v1/channels/${t.ref}`;
        case 'code':
            return `/v1/repos/${t.ref}`;
        case 'websites':
            return `/v1/projects/${t.ref}`;
        case 'databases':
            return `/v1/databases/${t.ref}`;
        case 'files':
            return `/v1/buckets/${t.ref}`;
        case 'machines':
            return t.place?.kind === 'own' ? `/v1/machines/${t.ref}` : null;
        default:
            return null;
    }
}

/** Why it isn't deleted here, or null. */
export function deleteRefusal(t: Thing, owner?: string): string | null {
    if (t.kind === 'memories' && t.knowledge?.kind === 'memory' && t.knowledge.agentId) return `It goes with ${owner ?? 'its agent'}; delete ${owner ?? 'the agent'} to delete it`;
    if (t.kind === 'machines' && t.place?.kind !== 'own') return t.machine?.agentId ? 'It goes with its agent' : 'It stops by itself';
    if (t.kind === 'numbers' || t.kind === 'email') return 'Released from its page in Resources';
    return null;
}

/** Every read a change to the space or the account's items moves. */
function readAgain(spaceId: string) {
    readSpaceAgain(spaceId);
    invalidateV1(SPACES_KEY);
    invalidateV1(AGENTS_KEY);
    invalidateV1(SKILLS_KEY);
    invalidateV1(MEMORIES_KEY);
    invalidateV1(CONNECTIONS_KEY);
    invalidateV1(SECRETS_KEY);
    invalidateV1(OWN_KEY);
    invalidateV1('resources:');
}

async function addOne(client: NoClick, spaceId: string, t: Thing): Promise<() => Promise<void>> {
    if (t.kind === 'agents') {
        const member = await space(client, spaceId).add(Agent.fromId(t.ref, { client }));
        return () => space(client, spaceId).remove(member.id);
    }
    const kind = LINK_KIND[t.kind];
    if (!kind) throw new Error(`${titleFor(t)} can’t be shared with a space.`);
    const link = await share(client, spaceId, kind, t.ref);
    return () => unshare(client, link);
}

/** Adds the account's items to the space: an agent joins it, anything else is shared with its people. From home, the
 *  space is named. */
export async function addToSpace(client: NoClick, spaceId: string, things: Thing[], named?: string): Promise<void> {
    const undo: (() => Promise<void>)[] = [];
    for (const t of things) {
        try {
            undo.push(await addOne(client, spaceId, t));
        } catch (error) {
            failed(`Couldn’t add ${titleFor(t)}`, error);
        }
    }
    readAgain(spaceId);
    if (!undo.length) return;
    const one = undo.length === 1 && things.length === 1 ? things[0] : null;
    const where = named ?? 'this space';
    const agents = things.every((t) => t.kind === 'agents');
    toast(one ? (named && !agents ? `${titleFor(one)} is shared with ${named}` : `${titleFor(one)} is in ${where}`) : `${undo.length} added to ${where}`, {
        description: agents ? `It works in ${named ? `${named}’s` : 'this space’s'} channels now.` : `Everyone in ${where} gets it now, and anyone who joins later.`,
        action: { label: 'Undo', onClick: () => void Promise.all(undo.map((u) => u())).then(() => readAgain(spaceId)) },
    });
}

/** Takes it out of the space: people here lose it; it stays in the account, and agents that use it as their own keep it. */
export async function removeFromSpace(client: NoClick, spaceId: string, t: Thing, elsewhere: string[]): Promise<void> {
    let undo: () => Promise<unknown>;
    try {
        if (t.kind === 'agents') {
            await space(client, spaceId).remove(Agent.fromId(t.ref, { client }));
            undo = () => space(client, spaceId).add(Agent.fromId(t.ref, { client }));
        } else if (t.link) {
            const link: SpaceLink = t.link;
            await unshare(client, link);
            undo = async () => {
                const back = await share(client, spaceId, link.kind, link.ref);
                await setLevels(client, back, { membersLevel: link.membersLevel, guestsLevel: link.guestsLevel });
            };
        } else return;
    } catch (error) {
        failed(`Couldn’t take ${titleFor(t)} out of this space`, error);
        return;
    }
    readAgain(spaceId);
    toast(`${titleFor(t)} is out of this space`, {
        description:
            t.kind === 'agents'
                ? `It stays yours${elsewhere.length ? ` and stays in ${list(elsewhere)}` : ''}.`
                : 'People here lose it. It stays in the account, and agents that use it as their own keep it.',
        action: { label: 'Undo', onClick: () => void undo().then(() => readAgain(spaceId)) },
    });
}

export async function changeLevel(client: NoClick, spaceId: string, link: SpaceLink, who: 'members' | 'guests', level: string): Promise<void> {
    try {
        await setLevels(client, link, who === 'members' ? { membersLevel: level } : { guestsLevel: level });
        readSpaceAgain(spaceId);
    } catch (error) {
        failed('Couldn’t change what people here get', error);
    }
}

export async function renameThing(client: NoClick, spaceId: string, t: Thing, name: string): Promise<void> {
    try {
        if (t.kind === 'channels') await Channel.fromId(t.ref, { client }).update({ name });
        else if (t.knowledge) await renameKnowledge(client, t.knowledge, name);
        readAgain(spaceId);
    } catch (error) {
        failed(`Couldn’t rename ${titleFor(t)}`, error);
    }
}

/** What a call does, as the platform previews it before anything goes: what it deletes, what depends on it, what's lost. */
export interface Impact {
    deletes: string;
    dependsOnIt: string[];
    dataLost: string[];
    reversible: boolean;
    /** How it comes back, where it does ("Restorable from the trash for 30 days."). */
    undo: string | null;
}

/** The platform's preview of `method path` (`POST /v1/delete_previews`). */
export async function previewCall(client: NoClick, path: string, method = 'DELETE'): Promise<Impact> {
    const { impact } = await client.request<{ impact: Record<string, unknown> }>('POST', '/v1/delete_previews', { json: { method, path } });
    const strings = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);
    return { deletes: String(impact.deletes ?? ''), dependsOnIt: strings(impact.depends_on_it), dataLost: strings(impact.data_lost), reversible: impact.reversible !== false, undo: typeof impact.undo === 'string' ? impact.undo : null };
}

/** What deleting it does, as the platform previews it (the agents, apps, spaces and sign-ins that lose it), else null. */
export async function previewDelete(client: NoClick, t: Thing): Promise<Impact | null> {
    const path = deletePath(t);
    if (!path || t.kind === 'machines') return null;
    return previewCall(client, path);
}

/** Takes a secret off every agent that holds it and deletes it; resolves false when it couldn't. */
async function removeSecretThing(client: NoClick, spaceId: string, t: Thing): Promise<boolean> {
    let from: string[];
    try {
        from = await removeSecret(client, t.secret!);
    } catch (error) {
        readAgain(spaceId);
        failed(`Couldn’t remove ${titleFor(t)}`, error);
        return false;
    }
    readAgain(spaceId);
    toast(`Removed ${titleFor(t)}`, { description: from.length ? `It came off ${list(from)}, and it’s deleted.` : 'It’s deleted.' });
    return true;
}

/** Deletes it from the account (to the trash where its kind has one); resolves false when it couldn't. */
export async function deleteThing(client: NoClick, spaceId: string, t: Thing): Promise<boolean> {
    if (t.kind === 'secrets') return removeSecretThing(client, spaceId, t);
    const path = deletePath(t);
    if (!path) return false;
    let trashId: string | null = null;
    try {
        const raw = await client.request<{ trash?: { id?: string } } | null>('DELETE', path);
        trashId = raw?.trash?.id ?? null;
    } catch (error) {
        failed(`Couldn’t delete ${titleFor(t)}`, error);
        return false;
    }
    readAgain(spaceId);
    toast(trashId ? `${titleFor(t)} is in the trash` : removedForGood(t) ? `Removed ${titleFor(t)}` : `${titleFor(t)} is deleted`, {
        description: trashId ? 'Gone from every space and agent. Restore it from Resources within 30 days.' : undefined,
        action: trashId ? { label: 'Undo', onClick: () => void TrashItem.fromId(trashId!, { client }).restore().then(() => readAgain(spaceId)) } : undefined,
    });
    return true;
}
