// Skills, memories and machines as Resources lists them: the words each row and page show, the agents that use each
// (a row names the first), what a machine costs where it has a price of its own, and how a skill or memory goes to
// the trash (detached from every agent, which the platform's preview names). An agent's own memory is listed after
// the account's named ones, under its agent's name; it goes only with its agent.
import { countOf, fmtBytes } from '@/ui/primitives';
import type { ResourceItem } from '@/screens/resources/model';
import type { DeletionImpact, Removal } from '@/screens/resources/platform';
import type { NoClick } from 'noclick';
import { REGION_NAMES } from '@/lib/regionNames';
import { removeMachine, trashKnowledge, type AgentRef, type Compute, type Knowledge, type MemoryItem, type OwnComputer, type Skill } from './knowledge';

/** Agents' names as Work shows them, by id (the account's coordinator is NoClick); the API's own name otherwise. */
type Names = ReadonlyMap<string, string>;
const agentUser = (a: { id: string; name: string }, names?: Names) => ({ kind: 'agent' as const, id: a.id, name: names?.get(a.id) ?? a.name, binding: null });

export function skillItem(s: Skill, names?: Names): ResourceItem {
    return {
        id: s.id,
        kind: 'skills',
        title: s.name,
        subtitle: s.description,
        updatedAt: s.updatedAt,
        usedBy: [],
        users: s.attachedTo.map((a) => agentUser(a, names)),
        platform: {
            facts: [
                ['Version', `v${s.version}`],
                ['Files', `${countOf(s.fileCount, 'file')} · ${fmtBytes(s.size)}`],
                ['Read', s.always ? 'In every turn' : 'When it’s needed'],
            ],
            usersInBody: true,
        },
    };
}

export function memoryItem(m: MemoryItem, agents: ReadonlyMap<string, AgentRef>): ResourceItem {
    const owner = m.agentId ? agents.get(m.agentId) : undefined;
    return {
        id: m.id,
        kind: 'memories',
        title: owner ? `${owner.name}’s memory` : (m.name ?? ''),
        subtitle: m.description,
        updatedAt: m.updatedAt,
        usedBy: [],
        users: [...(owner ? [agentUser(owner)] : []), ...m.attachedTo.map((a) => agentUser(a, new Map([...agents].map(([id, ref]) => [id, ref.name]))))],
        platform: {
            facts: [
                ...(m.entryCount !== null ? ([['Entries', String(m.entryCount)]] as [string, string][]) : []),
                ['Written by', owner ? `${owner.name} alone` : m.attachedTo.some((a) => a.writes) ? 'People and agents' : 'People'],
            ],
            usersInBody: true,
        },
    };
}

/** What a machine's row adds from its own read (`GET /v1/machines`): who's on it, its size, when it last booted, and
 *  for one held until NoClick approves the company, whose. */
export interface PlaceExtra {
    agents?: string[];
    size?: string | null;
    startedAt?: string | null;
    status?: string;
    os?: string | null;
    company?: string | null;
}

const SIZE_WORDS: Record<string, string> = { small: 'Small', medium: 'Medium', large: 'Large', xlarge: 'XLarge' };

/** "12 days", "3 hours", "just now". */
function upFor(from: string, now: number): string {
    const m = Math.max(0, Math.floor((now - Date.parse(from)) / 60_000));
    if (m < 2) return 'just now';
    if (m < 60) return `${m} minutes`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} ${h === 1 ? 'hour' : 'hours'}`;
    const d = Math.floor(h / 24);
    return `${d} ${d === 1 ? 'day' : 'days'}`;
}

/** A machine, a sandbox up now, or a computer of yours: its row says how it stands and who's on it, where it runs as a
 *  place, and a machine's price a month. */
export function placeItem(p: Compute | OwnComputer, names?: Names, extra: PlaceExtra = {}, now = Date.now()): ResourceItem {
    const on = extra.agents?.length ? extra.agents.join(', ') : null;
    if (p.kind === 'own') {
        const pairing = p.status === 'provisioning';
        const state = pairing ? (p.pairing?.installingOn ? `Installing on ${p.pairing.installingOn}` : 'Waiting to connect') : p.status === 'running' ? 'Online' : 'Offline';
        const mac = /\(VM on macOS/.test(extra.os ?? p.os ?? '');
        return {
            id: p.id,
            kind: 'machines',
            title: p.name || 'Your computer',
            subtitle: [state, pairing ? null : (on ?? 'no agents yet')].filter(Boolean).join(' · '),
            where: mac ? 'Your Mac' : 'Your computer',
            updatedAt: p.lastSeenAt ?? p.createdAt,
            usedBy: [],
            pending: pairing ? 'Run its pairing command on the computer to finish adding it.' : undefined,
            price: null,
            platform: { facts: [], usersInBody: true },
        };
    }
    const users = p.running.map((r) => agentUser({ id: r.agentId, name: r.agentName }, names));
    if (p.kind !== 'machine') {
        return {
            id: p.id,
            kind: 'machines',
            // An agent's sandbox is named for its agent.
            title: p.kind === 'agent_sandbox' && users[0] ? users[0].name : p.name,
            subtitle: `${p.kind === 'agent_sandbox' ? 'Cloud sandbox' : 'Developer sandbox'} · up now`,
            where: p.region ? (REGION_NAMES[p.region] ?? p.region) : undefined,
            updatedAt: p.startedAt,
            usedBy: [],
            users,
            price: p.usdPerMonth !== null ? { usd: p.usdPerMonth, per: 'month' } : undefined,
            platform: { facts: [], usersInBody: true },
        };
    }
    const status = extra.status ?? p.status;
    const size = extra.size ? SIZE_WORDS[extra.size] ?? extra.size : null;
    const held = status === 'awaiting_approval';
    const state = held
        ? `Waiting for NoClick to approve ${extra.company || 'your company'}`
        : status === 'running'
          ? extra.startedAt
              ? `Up ${upFor(extra.startedAt, now)}`
              : 'Running'
          : status === 'provisioning'
            ? 'Starting · ready in about 3 minutes'
            : status === 'updating'
              ? 'Resizing'
              : status.charAt(0).toUpperCase() + status.slice(1);
    return {
        id: p.id,
        kind: 'machines',
        title: p.name,
        subtitle: [state, held ? size : (on ?? (status === 'running' ? 'no agents yet' : null))].filter(Boolean).join(' · '),
        where: p.region ? (REGION_NAMES[p.region] ?? p.region) : undefined,
        updatedAt: p.startedAt,
        usedBy: [],
        users,
        attention: status === 'failed' ? 'This machine failed. Its agents can’t run here until it’s restarted.' : undefined,
        pending: held ? `It starts the moment NoClick approves ${extra.company || 'your company'}. Nothing is charged until then.` : undefined,
        price: p.usdPerMonth !== null ? { usd: p.usdPerMonth, per: 'month' } : undefined,
        platform: { facts: [], usersInBody: true },
    };
}

/** How a skill's or named memory's page moves it to the trash; an agent's own memory goes only with its agent. */
export function knowledgeRemoval(client: NoClick, item: Knowledge, preview: (path: string) => Promise<DeletionImpact>): Removal | null {
    if (item.kind === 'memory' && item.agentId) return null;
    const path = `/v1/${item.kind === 'skill' ? 'skills' : 'memories'}/${item.id}`;
    return {
        label: 'Move to trash',
        confirm: `Move ${item.name} to the trash`,
        preview: () => preview(path),
        run: async () => {
            await trashKnowledge(client, item);
            return { done: `Moved ${item.name} to the trash`, gone: true };
        },
    };
}

/** How a machine's page removes it: a computer of yours stops being used (it uninstalls NoClick at its next check-in),
 *  a NoClick machine is deleted with its disk; a sandbox goes by itself. Machines have no platform preview, so what it
 *  does is said from what the list knows. */
export function placeRemoval(client: NoClick, place: Compute | OwnComputer): Removal | null {
    if (place.kind !== 'own' && place.kind !== 'machine') return null;
    const running = place.kind === 'machine' ? place.running.map((r) => r.agentName) : [];
    const own = place.kind === 'own';
    return {
        label: own ? 'Remove' : 'Delete',
        confirm: own ? `Remove ${place.name}` : `Delete ${place.name}`,
        preview: async () => ({
            deletes: own ? `NoClick stops running agents on ${place.name}; it uninstalls NoClick the next time it checks in.` : `Deletes the machine ${place.name} and its disk; its agents move back to their own cloud sandboxes.`,
            depends_on_it: running,
            data_lost: own ? [] : ['Everything on its disk'],
            stops_billing: !own && place.usdPerMonth ? [`$${place.usdPerMonth.toFixed(2)} a month`] : [],
            reversible: false,
            undo: own ? 'Add it again any time with a new pairing command.' : null,
        }),
        run: async () => {
            await removeMachine(client, place.id);
            return { done: own ? `Removed ${place.name}` : `Deleted ${place.name}`, gone: true };
        },
    };
}
