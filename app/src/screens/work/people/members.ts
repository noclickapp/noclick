// Who's in a space and how they got there: its people (with each one's role, and you among them), its agents, how
// many people its plan allows, and its open invites (for those who may invite), read through the space's client and
// read again when a `workspace` frame says something moved. Every change goes through the same client; a failure
// becomes the sentence to show.
import { useMemo } from 'react';
import { errorText } from '@/screens/console/pages/resources/shared';
import { Agent, Workspace, type NoClick, type WorkspaceInvite, type WorkspaceMember, type WorkspaceRole } from 'noclick';
import { keptByNoClick, useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import { useWorkFrames } from '@/sdk/live';

export interface SpacePeople {
    loading: boolean;
    error: string | null;
    /** What you are in it. */
    role: 'owner' | WorkspaceRole | null;
    people: WorkspaceMember[];
    /** Its agents, but NoClick's own: every space of the account's own holds it, and it works across the account. */
    agents: WorkspaceMember[];
    peopleCount: number;
    peopleLimit: number | null;
    /** Its active invites, for its owner and admins; empty for anyone else. */
    invites: WorkspaceInvite[];
    /** Whether you may invite and remove people. */
    manages: boolean;
    refresh(): void;
    setRole(member: WorkspaceMember, role: WorkspaceRole): Promise<void>;
    remove(member: WorkspaceMember): Promise<void>;
    addAgent(agentId: string): Promise<void>;
    /** A new share link as `role`, the one before it turned off. */
    newLink(role: WorkspaceRole): Promise<WorkspaceInvite>;
    invite(email: string, role: WorkspaceRole): Promise<WorkspaceInvite>;
    revoke(invite: WorkspaceInvite): Promise<void>;
    resend(invite: WorkspaceInvite): Promise<void>;
}

const said = async <T>(call: () => Promise<T>): Promise<T> => {
    try {
        return await call();
    } catch (e) {
        throw new Error(errorText(e));
    }
};

/** A space's people, kept per client and space: a return to the space (or to Work) shows them at once while they're
 *  read again, and a hover on its tile reads them ahead. */
export const peopleKey = (workspaceId: string) => `work:people:${workspaceId}`;
export async function readPeople(client: NoClick, workspaceId: string): Promise<{ space: Workspace; invites: WorkspaceInvite[] }> {
    const space = await Workspace.get(workspaceId, { client, user: null });
    const manages = space.role === 'owner' || space.role === 'admin';
    return { space, invites: manages ? await space.invites({ status: 'active' }) : [] };
}

export function useSpacePeople(workspaceId: string | null): SpacePeople {
    const client = useWorkClient();
    const people = useWorkV1(workspaceId ? peopleKey(workspaceId) : null, (c) => readPeople(c, workspaceId!));
    const space = people.data?.space ?? null;
    const invites = useMemo(() => people.data?.invites ?? [], [people.data]);
    const state = { loading: people.loading, error: people.error ? errorText(people.error) : null };
    const { refresh: read } = people;
    useWorkFrames('platform:channel', (frame) => {
        if (frame.kind === 'workspace' && (!frame.workspace_id || frame.workspace_id === workspaceId)) void read();
    });

    return useMemo<SpacePeople>(() => {
        const role = space?.role ?? null;
        const members = space?.members ?? [];
        const handle = () => {
            if (!space) throw new Error('The space hasn’t loaded yet.');
            return space;
        };
        return {
            loading: state.loading,
            error: state.error,
            role,
            people: members.filter((m) => m.type === 'user'),
            agents: members.filter((m) => m.type === 'agent' && !keptByNoClick(m.raw)),
            peopleCount: space?.peopleCount ?? 0,
            peopleLimit: space?.peopleLimit ?? null,
            invites,
            manages: role === 'owner' || role === 'admin',
            refresh: () => void read(),
            setRole: (member, next) => said(async () => void (await handle().setRole(member, next), await read())),
            remove: (member) => said(async () => void (await handle().remove(member), await read())),
            addAgent: (agentId) => said(async () => void (await handle().add(Agent.fromId(agentId, { client, user: null })), await read())),
            newLink: (next) =>
                said(async () => {
                    const made = await handle().inviteLink({ role: next });
                    for (const old of invites.filter((i) => i.type === 'link' && i.id !== made.id)) await old.revoke();
                    await read();
                    return made;
                }),
            invite: (email, next) =>
                said(async () => {
                    const made = await handle().invite(email, { role: next });
                    await read();
                    return made;
                }),
            revoke: (invite) => said(async () => void (await invite.revoke(), await read())),
            resend: (invite) => said(async () => void (await invite.resend(), await read())),
        };
    }, [space, invites, state.loading, state.error, read, client]);
}
