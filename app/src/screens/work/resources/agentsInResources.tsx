// The account's agents on its Resources page, where what each one costs is read: every agent the account owns, whatever
// space it's in (`useAgentEntries(null)`: never a NoClick, nor one of NoClick's helpers), each with its face and
// ring, what it's doing, where it works (an agent is the account's, and any number of its spaces can have it) and what
// it has cost this month. A row opens the agent's own page here (agentPage.tsx: its files, spend and sessions, and Open
// in Work), and its ⋯ menu renames it. Drawn inside PlatformReads, which provides Work's client.
import { createContext, useContext, useMemo } from 'react';
import { MoreHorizontal, Pencil } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { useAgentMonthSpend } from '@/screens/console/agentParts';
import type { ResourceItem } from '@/screens/resources/model';
import type { ChannelMember } from '@/screens/channels/types';
import { AgentRing, WorkMotion } from '../agents/AgentRing';
import { useAgentEntries } from '../agents/AgentsList';
import { useAgentFrames, useAgents, useWorkV1 } from '../agents/reads';
import { renamable, useRenameDialog } from '../agents/rename';
import type { Entry } from '../agents/states';
import { readSpaces, spacesByAgent, SPACES_KEY } from './space/data';
import { few } from './space/parts';

/** Each listed agent's row as its lead draws it: its state and its face. */
interface AgentLeads {
    entries: ReadonlyMap<string, Entry>;
    faces: ReadonlyMap<string, ChannelMember>;
}
const AgentLeadsContext = createContext<AgentLeads>({ entries: new Map(), faces: new Map() });
export const AgentLeadsProvider = AgentLeadsContext.Provider;
export const useAgentLeads = () => useContext(AgentLeadsContext);

/** Where an agent works, as its row says it: the spaces it's in, else your account. */
export function whereItWorks(spaces: readonly string[]): string {
    return spaces.length ? `Works in ${few([...spaces])}` : 'Your account';
}

/** The account's agents as Resources lists them, most spent this month first; `leads` is what their rows' leads read. */
export function useAccountAgentItems(): { items: ResourceItem[]; leads: AgentLeads; loading: boolean; error: unknown } {
    useAgentFrames();
    const { entries, faces, loading, states } = useAgentEntries(null, { ticking: false });
    const agents = useAgents();
    const spaces = useWorkV1(SPACES_KEY, readSpaces);
    const spentBy = useAgentMonthSpend(agents.data ?? []);
    const items = useMemo(() => {
        const byId = new Map((agents.data ?? []).map((a) => [a.id, a]));
        const memberOf = spacesByAgent(spaces.data ?? []);
        const spent = (id: string) => {
            const agent = byId.get(id);
            return agent ? spentBy(agent) : undefined;
        };
        return entries
            .map((e): ResourceItem => {
                const usd = spent(e.id);
                return {
                    id: e.id,
                    kind: 'agents',
                    title: e.name,
                    subtitle: e.line,
                    usedBy: [],
                    where: whereItWorks(memberOf.get(e.id) ?? []),
                    ...(e.status === 'failed' ? { attention: e.line } : {}),
                    ...(typeof usd === 'number' ? { price: { usd, per: 'so-far' as const } } : {}),
                };
            })
            .sort((a, b) => (b.price?.usd ?? 0) - (a.price?.usd ?? 0));
    }, [entries, agents.data, spaces.data, spentBy]);
    const leads = useMemo(() => ({ entries: new Map(entries.map((e) => [e.id, e])), faces }), [entries, faces]);
    return { items, leads, loading, error: states.error ?? agents.error };
}

/** An agent's row leads with its face, its state drawn as a ring round it (`size` across; its page's header's larger). */
export function AgentLead({ item, size = 32 }: { item: ResourceItem; size?: 32 | 48 }) {
    const { entries, faces } = useContext(AgentLeadsContext);
    const entry = entries.get(item.id);
    return (
        <span className="grid shrink-0 place-items-center" style={{ width: size + 4, height: size + 4 }}>
            <WorkMotion />
            <AgentRing member={faces.get(item.id) ?? { id: item.id, kind: 'agent', name: item.title }} status={entry?.status ?? 'idle'} size={size} />
        </span>
    );
}

/** An agent's row's ⋯ menu: Rename (Resources lists no NoClick; one built in the app keeps its automation's name). There
 *  on a touch screen too, where nothing hovers. */
export function AgentRowMenu({ item }: { item: ResourceItem }) {
    const renaming = useRenameDialog();
    if (!renamable({ id: item.id })) return null;
    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    aria-label={`More for ${item.title}`}
                    className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground max-md:h-10 max-md:w-10"
                >
                    <MoreHorizontal className="h-4 w-4" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" sideOffset={4} className="min-w-[180px] rounded-xl p-1">
                    <DropdownMenuItem onSelect={() => renaming.ask({ id: item.id, name: item.title })} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                        <Pencil className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
                        Rename
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            {renaming.dialog}
        </>
    );
}
