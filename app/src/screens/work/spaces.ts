// The spaces Work shows: your account's own workspaces and the ones you joined in other accounts (`Workspace.mine`),
// read through the dashboard's client and read again when a `workspace` frame says one moved (a slow re-read is the
// backstop); making, changing and leaving one; and the client a space's views read with: the dashboard's for your
// own, a session acting as you in that account for one you joined (minted again before it lapses). An archived space
// stays listed, read-only, until it's unarchived; a deleted one goes to the trash with all it held. Your personal space
// is Work's home: once you share it, the workspace holding its people is home's own, never a space of its own.
import { useEffect, useMemo, useState } from 'react';
import { errorText } from '@/screens/console/pages/resources/shared';
import { peekV1 } from '@/sdk/useV1';
import { TrashItem, Workspace, type MyWorkspace, type NoClick } from 'noclick';
import { useWorkV1 } from './agents/reads';
import { useWorkClient } from './client';
import { useWorkFrames } from '@/sdk/live';
import { HOME_SPACE } from './place';

export type SpaceRole = 'owner' | 'admin' | 'member' | 'guest';

export interface WorkSpace {
    /** The workspace's id, or `HOME_SPACE` for your channels in none. */
    id: string;
    /** The platform workspace; null for home. */
    workspaceId: string | null;
    name: string;
    logoUrl?: string;
    /** Your account's own (else one you joined). */
    own: boolean;
    /** What you are in it. */
    role: SpaceRole;
    /** Whose it is, for one you joined. */
    accountName?: string;
    /** Your user id in its account, for one you joined: how its messages name you. */
    userId?: string;
    /** Archived: everything in it is read, nothing posted. */
    archived?: boolean;
    /** Someone's personal space they shared with you: their own channels, never a space of theirs to change. */
    personal?: boolean;
    /** Your personal space's workspace once you've shared it: its people, invites and DMs. */
    sharedId?: string;
}

/** How a sentence names a space: Work's home is your personal space. */
export const spaceWhere = (space: Pick<WorkSpace, 'workspaceId' | 'name'>) => (space.workspaceId ? space.name : 'your personal space');

/** Your channels in no space, named for you and wearing your picture (`picture`, where you have one). */
export function homeSpace(name: string, picture?: string): WorkSpace {
    return { id: HOME_SPACE, workspaceId: null, name, ...(picture ? { logoUrl: picture } : {}), own: true, role: 'owner' };
}

function spaceOf(w: MyWorkspace): WorkSpace {
    return {
        id: w.id,
        workspaceId: w.id,
        name: w.name,
        logoUrl: w.logoUrl ?? undefined,
        own: w.own,
        role: w.role,
        accountName: w.accountName ?? undefined,
        userId: w.userId ?? undefined,
        ...(w.status === 'archived' ? { archived: true } : {}),
        ...(w.raw.personal === true ? { personal: true } : {}),
    };
}

/** How often they're read again when no frame came. */
const BACKSTOP_MS = 60_000;

export interface Spaces {
    loading: boolean;
    error: string | null;
    /** Your spaces and the ones you joined; your own personal space is Work's home, never among them. */
    spaces: WorkSpace[];
    /** Your personal space's workspace, once you've shared it. */
    personalId: string | null;
    /** Your personal space as a space people can join (its workspace, made the first time): its id. */
    sharePersonal(): Promise<string>;
    /** Read them again; resolves once they're read. */
    refresh(): Promise<void>;
    create(name: string, logo?: File): Promise<WorkSpace>;
    /** Rename it, and give it a new logo when one is picked, through the space's own client. */
    update(space: WorkSpace, name: string, logo: File | undefined, via: NoClick): Promise<void>;
    /** Leave one you joined. */
    leave(space: WorkSpace): Promise<void>;
    /** Archive one of yours, or make it active again. */
    archive(space: WorkSpace, archived: boolean): Promise<void>;
    /** One of yours to the trash with everything in it; resolves to its trash item, which `restore` puts back. */
    remove(space: WorkSpace): Promise<{ trashId: string }>;
    restore(trashId: string): Promise<void>;
}

/** Your spaces, read once for this client and kept: a return to Work shows them at once while they're read again. */
export const MINE_KEY = 'work:my-spaces';

export function useSpaces(): Spaces {
    const client = useWorkClient();
    const read = useWorkV1(MINE_KEY, async (c) => (await Workspace.mine({ client: c })).map(spaceOf), { pollMs: BACKSTOP_MS });
    useWorkFrames('platform:channel', (frame) => {
        if (frame.kind === 'workspace') void read.refresh();
    });
    const { data, error, loading, mutate, refresh } = read;

    return useMemo<Spaces>(() => {
        const latest = () => peekV1<WorkSpace[]>(client, MINE_KEY) ?? [];
        const keep = (space: WorkSpace) => mutate(latest().some((s) => s.id === space.id) ? latest().map((s) => (s.id === space.id ? space : s)) : [...latest(), space]);
        const yours = (s: WorkSpace) => s.own && s.personal;
        return {
            loading,
            error: error ? errorText(error) : null,
            spaces: (data ?? []).filter((s) => !yours(s)),
            personalId: (data ?? []).find(yours)?.id ?? null,
            sharePersonal: async () => {
                try {
                    const raw = await Workspace.personalSpace({ client });
                    keep({ id: raw.id, workspaceId: raw.id, name: raw.name, own: true, role: 'owner', personal: true });
                    return raw.id;
                } catch (e) {
                    throw new Error(errorText(e));
                }
            },
            refresh: () => refresh(),
            create: async (name, logo) => {
                try {
                    let made = await Workspace.create(name, { client, user: null });
                    if (logo) made = await made.setLogo(logo, { mimeType: logo.type || undefined });
                    const space: WorkSpace = { id: made.id, workspaceId: made.id, name: made.name, logoUrl: made.logoUrl ?? undefined, own: true, role: 'owner' };
                    keep(space);
                    return space;
                } catch (e) {
                    throw new Error(errorText(e));
                }
            },
            update: async (space, name, logo, via) => {
                if (!space.workspaceId || (name === space.name && !logo)) return;
                try {
                    let changed = Workspace.fromId(space.workspaceId, { client: via, user: null });
                    if (name !== space.name) changed = await changed.update({ name });
                    if (logo) changed = await changed.setLogo(logo, { mimeType: logo.type || undefined });
                    keep({ ...space, name: changed.name, logoUrl: changed.logoUrl ?? undefined });
                } catch (e) {
                    throw new Error(errorText(e));
                }
            },
            leave: async (space) => {
                try {
                    await Workspace.leave(space.id, { client });
                    mutate(latest().filter((s) => s.id !== space.id));
                } catch (e) {
                    throw new Error(errorText(e));
                }
            },
            archive: async (space, archived) => {
                if (!space.workspaceId) return;
                try {
                    const it = Workspace.fromId(space.workspaceId, { client, user: null });
                    await (archived ? it.archive() : it.unarchive());
                    keep({ ...space, archived });
                } catch (e) {
                    throw new Error(errorText(e));
                }
            },
            remove: async (space) => {
                if (!space.workspaceId) throw new Error('Your personal space can’t be deleted.');
                try {
                    const trashed = await Workspace.fromId(space.workspaceId, { client, user: null }).delete();
                    mutate(latest().filter((s) => s.id !== space.id));
                    return { trashId: trashed.id };
                } catch (e) {
                    throw new Error(errorText(e));
                }
            },
            restore: async (trashId) => {
                try {
                    await TrashItem.fromId(trashId, { client }).restore();
                } catch (e) {
                    throw new Error(errorText(e));
                }
                await refresh();
            },
        };
    }, [data, error, loading, mutate, refresh, client]);
}

/** A session lasts an hour; a new one is minted this long before it lapses. */
const SESSION_TTL_S = 3600;
const RENEW_BEFORE_MS = 5 * 60_000;

interface Minted {
    spaceId: string;
    client: NoClick;
    renewAt: number;
}

/** The sessions minted for joined spaces, per client: a return to a space reuses its session (and so everything its
 *  client read) until it's due to be renewed. */
const sessions = new WeakMap<NoClick, Map<string, Minted>>();
const sessionOf = (client: NoClick, spaceId: string | null) => {
    const held = spaceId ? sessions.get(client)?.get(spaceId) : undefined;
    return held && held.renewAt > Date.now() ? held : null;
};

/** The client a space's views read and write with; null while a joined space's session is being minted. */
export function useSpaceClient(space: WorkSpace): { client: NoClick | null; error: string | null } {
    const client = useWorkClient();
    const joined = !space.own && space.workspaceId ? space.workspaceId : null;
    const [minted, setMinted] = useState<Minted | null>(() => sessionOf(client, joined));
    const [error, setError] = useState<string | null>(null);
    const current = minted && minted.spaceId === joined ? minted : null;

    useEffect(() => {
        if (!joined) return;
        let live = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const renewAfter = (at: number) => (timer = setTimeout(mint, Math.max(30_000, at - Date.now())));
        const mint = () =>
            Workspace.session(joined, { client, ttlS: SESSION_TTL_S }).then(
                (session) => {
                    if (!live) return;
                    const made: Minted = { spaceId: joined, client: session.client({ baseUrl: client.baseUrl }), renewAt: (session.expiresAt?.getTime() ?? Date.now() + SESSION_TTL_S * 1000) - RENEW_BEFORE_MS };
                    let held = sessions.get(client);
                    if (!held) sessions.set(client, (held = new Map()));
                    held.set(joined, made);
                    setMinted(made);
                    setError(null);
                    renewAfter(made.renewAt);
                },
                (e) => live && setError(errorText(e))
            );
        const held = sessionOf(client, joined);
        if (held) {
            setMinted(held);
            renewAfter(held.renewAt);
        } else void mint();
        return () => {
            live = false;
            if (timer) clearTimeout(timer);
        };
    }, [joined, client]);

    if (!joined) return { client, error: null };
    return { client: current?.client ?? null, error: current ? null : error };
}
