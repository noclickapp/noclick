// The account's secrets as Resources and a space's tab show them: each by name, where an agent holding it finds it
// (an environment variable, a file, or neither when a tool server's sign-in reads it), the agents that hold it, and
// the computer it was moved from. Only names are read: a value never leaves the API. Removing one takes it off each
// agent that holds it, then deletes it, which also ends any sign-in made of its value.
import { ALL_USERS, Agent, Secret, type NoClick } from 'noclick';
import type { ResourceItem } from '@/screens/resources/model';
import type { DeletionImpact, Removal } from '@/screens/resources/platform';
import { movedFacts, movedFrom, movedLine, type MovedFrom } from '@/lib/movedFrom';

export const SECRETS_KEY = 'resources:secrets';

/** The key a moved file's value travels in, which the copy's setup writes to the file. */
const FILE_KEY = 'MOVED_FILE_';
/** The key a moved secret holds when nothing of its own puts it in the environment (a header's, a clone's). */
const VALUE_KEY = 'VALUE';

export interface SecretItem {
    id: string;
    name: string;
    keys: string[];
    userId: string | null;
    /** The agents that hold it. */
    agents: { id: string; name: string }[];
    movedFrom: MovedFrom | null;
    createdAt: string | null;
    updatedAt: string | null;
}

export function toSecret(s: Secret): SecretItem {
    return {
        id: s.id,
        name: s.name,
        keys: s.keys,
        userId: s.userId,
        agents: s.usedBy.filter((u) => u.kind === 'agent').map((u) => ({ id: u.id, name: u.name })),
        movedFrom: movedFrom(s.raw.moved_from),
        createdAt: s.createdAt?.toISOString() ?? null,
        updatedAt: s.updatedAt?.toISOString() ?? null,
    };
}

/** Every secret the account holds, its users' too. */
export async function listSecrets(client: NoClick): Promise<SecretItem[]> {
    return (await Secret.list({ client, userFilter: ALL_USERS })).map(toSecret);
}

/** Where an agent holding it finds it. */
export type Installed = { kind: 'env'; names: string[] } | { kind: 'file'; path: string | null; mode: string | null } | { kind: 'sign-in' };

export function installedAs(s: SecretItem): Installed {
    const to = s.movedFrom?.to;
    if (to?.file || (s.movedFrom && s.keys.some((k) => k.startsWith(FILE_KEY)))) return { kind: 'file', path: to?.file ?? null, mode: to?.mode ?? null };
    if (s.movedFrom && (to ? !to.env : s.keys.length === 1 && s.keys[0] === VALUE_KEY)) return { kind: 'sign-in' };
    return { kind: 'env', names: s.keys };
}

/** Where it is, in a line: "GH_TOKEN", "~/.config/gcloud/key.json". */
export function installedLine(i: Installed): string {
    if (i.kind === 'env') return i.names.length ? `Environment: ${i.names.join(', ')}` : 'Environment';
    if (i.kind === 'file') return i.path ? `File: ${i.path}` : 'A file';
    return 'Read by a tool server’s sign-in';
}

/** Its facts on a page: where it is and its keys, never a value. */
export function installedFacts(i: Installed): [string, string][] {
    if (i.kind === 'env') return [['Installed as', i.names.length === 1 ? 'An environment variable' : 'Environment variables'], [i.names.length === 1 ? 'Name' : 'Names', i.names.join(', ') || 'None yet']];
    if (i.kind === 'file') return [['Installed as', 'A file'], ['Path', i.path ?? 'Not recorded'], ...((i.mode ? [['Mode', i.mode]] : []) as [string, string][])];
    return [['Installed as', 'Not in an environment'], ['Read by', 'A tool server’s sign-in']];
}

/** Takes it off every agent that holds it, then deletes it. Resolves to the agents it came off; throws an Error saying
 *  how far it got when a step fails. */
export async function removeSecret(client: NoClick, s: SecretItem): Promise<string[]> {
    // Its owner's: a user's secret, held by that user's agents; else the account's.
    const user = s.userId ?? null;
    const done: string[] = [];
    for (const agent of s.agents) {
        try {
            const held = await Agent.get(agent.id, { client, user });
            await held.update({ secrets: held.secretIds.filter((id) => id !== s.id) });
            done.push(agent.name);
        } catch (error) {
            throw new Error(`${done.length ? `It came off ${done.join(', ')}, but not` : 'It couldn’t be taken'} off ${agent.name}: ${error instanceof Error ? error.message : String(error)}`);
        }
    }
    try {
        await Secret.fromId(s.id, { client, user }).delete();
    } catch (error) {
        throw new Error(`${done.length ? `It came off ${done.join(', ')}, but it` : 'It'} couldn’t be deleted: ${error instanceof Error ? error.message : String(error)}`);
    }
    return done;
}

// ── on the account's Resources page ────────────────────────────────────────

/** A secret as Resources lists it: where it is and where it came from, the agents that hold it, never a value. */
export function secretItem(s: SecretItem, names?: ReadonlyMap<string, string>): ResourceItem {
    const where = installedAs(s);
    return {
        id: s.id,
        kind: 'secrets',
        title: s.name,
        subtitle: [installedLine(where), s.movedFrom ? movedLine(s.movedFrom) : null].filter(Boolean).join(' · '),
        updatedAt: s.updatedAt,
        usedBy: [],
        users: s.agents.map((a) => ({ kind: 'agent' as const, id: a.id, name: names?.get(a.id) ?? a.name, binding: null })),
        platform: { facts: [...installedFacts(where), ['Value', 'Never shown here'], ...(s.movedFrom ? movedFacts(s.movedFrom) : [])] },
    };
}

/** How a secret's page removes it: the platform's preview names every agent and sign-in that loses it, then it comes
 *  off each agent and is deleted. */
export function secretRemoval(client: NoClick, s: SecretItem, preview: (path: string, user: string | null) => Promise<DeletionImpact>): Removal {
    return {
        label: 'Remove',
        confirm: `Remove ${s.name}`,
        preview: async () => {
            const impact = await preview(`/v1/secrets/${s.id}`, s.userId);
            return { ...impact, deletes: `${impact.deletes} It comes off each agent that holds it first; a sandbox already running keeps it until it stops.` };
        },
        run: async () => {
            const from = await removeSecret(client, s);
            return { done: from.length ? `Removed ${s.name} from ${new Intl.ListFormat('en', { type: 'conjunction' }).format(from)}` : `Removed ${s.name}`, gone: true };
        },
    };
}
