// Where agents run, as Resources and a space's tab show one: a NoClick machine kept on, an agent's sandbox up now, a
// developer sandbox, or a computer of yours that runs NoClick's machine daemon. A machine (yours included) draws its
// own page's sections (`machine/MachineDetail`), and, for a computer of yours still pairing, the one command that pairs
// it; a sandbox, its facts and who runs on it.
import { useContext, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Box, ChevronRight, Laptop, RefreshCw, Server } from 'lucide-react';
import { WorkNavContext } from '../nav';
import { HarnessMark, harnessLabel } from '../agents/harness';
import { useWorkClient } from '../client';
import { invalidateV1 } from '@/sdk/useV1';
import { agentsOnMachines, listCompute, listOwnComputers, newPairing, type Compute, type OwnComputer } from '@/screens/resources/knowledge';
import { useWorkV1 } from '../agents/reads';
import { relTime } from '@/ui/primitives';
import { Section, Surface } from '@/screens/resources/ui';
import { CopyButton } from '@/ui/CopyButton';
import { formatDollars } from '@/lib/formatters';
import { cn } from '@/ui/utils';
import { MachineDetail } from '../machine/MachineDetail';
import { placeName as regionName } from '../machine/machineView';
import { COMPUTE_KEY, OWN_KEY } from '../machine/reads';
import { AgentFace, SMALL_SECONDARY } from './knowledge/parts';
import { useAgentNames } from './knowledge/store';

export { COMPUTE_KEY, OWN_KEY };
/** Whether agents run on machines here yet (under `resources:machines`, so a machine's frame reads it again). */
export const AGENTS_ENABLED_KEY = 'resources:machines/enabled';

/** Said wherever a computer of yours would be added or used while agents don't run on machines here. */
export const AGENTS_NOT_ENABLED = "Agents on machines aren't enabled on this deployment yet.";

/** False while agents don't run on machines on this deployment; undefined until it's read. */
export function useAgentsOnMachines(): boolean | undefined {
    return useWorkV1(AGENTS_ENABLED_KEY, agentsOnMachines).data;
}

export type Place = Compute | OwnComputer;

/** A machine, sandbox or computer of yours, as Resources' list read it. */
export function usePlace(id: string): Place | undefined {
    const compute = useWorkV1(COMPUTE_KEY, listCompute);
    const own = useWorkV1(OWN_KEY, listOwnComputers);
    return compute.data?.data.find((c) => c.id === id) ?? own.data?.find((o) => o.id === id);
}

export const isOwn = (p: Place): p is OwnComputer => p.kind === 'own';

/** Its mark: a machine, a sandbox, or a computer of yours. */
export function PlaceIcon({ place, className = 'h-4 w-4' }: { place: Place; className?: string }) {
    const Icon = isOwn(place) ? Laptop : place.kind === 'machine' ? Server : Box;
    return <Icon className={cn(className, 'text-foreground/75')} strokeWidth={1.75} />;
}

/** Its name as a person says it: an agent's sandbox is that agent's (named as Work shows the agent, from `names`). */
export function placeName(p: Place | undefined, names?: ReadonlyMap<string, string>): string | undefined {
    if (!p) return undefined;
    if (p.kind !== 'agent_sandbox') return p.name;
    const agent = p.running[0];
    return `${(agent && names?.get(agent.agentId)) || p.name}’s sandbox`;
}

/** How long since `from`, in a word or two: "4m", "3h", "12 days". */
function since(from: string, now: string): string {
    const m = Math.max(0, Math.floor((Date.parse(now) - Date.parse(from)) / 60_000));
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h`;
    const d = Math.floor(h / 24);
    return `${d} ${d === 1 ? 'day' : 'days'}`;
}

/** "Running 4m · $0.06 today", "Up 12 days", "Online · no agent runs here now", "Offline since 3h ago", "Waiting to be paired". */
export function placeState(p: Place, now: string): string {
    if (isOwn(p)) {
        if (p.status === 'provisioning') return p.pairing?.installingOn ? `Installing on ${p.pairing.installingOn}` : 'Waiting to be paired';
        if (p.status === 'offline') return p.lastSeenAt ? `Offline since ${relTime(p.lastSeenAt, now)}` : 'Offline';
        return p.status === 'running' ? 'Online' : p.status;
    }
    const today = p.spentUsdToday !== null ? ` · ${formatDollars(p.spentUsdToday)} today` : '';
    if (p.kind !== 'machine') return `${p.startedAt ? `Running ${since(p.startedAt, now)}` : 'Running'}${today}`;
    if (p.status === 'running') return p.startedAt ? `Up ${since(p.startedAt, now)}${today}` : 'Up';
    return p.status ? p.status.charAt(0).toUpperCase() + p.status.slice(1) : 'Unknown';
}

/** Up now: running, online, or a sandbox (only live ones are listed). */
export const placeUp = (p: Place) => (isOwn(p) ? p.status === 'running' : p.kind !== 'machine' || p.status === 'running');

/** What kind of place it is, in a few words. */
export function placeKind(p: Place): string {
    if (isOwn(p)) return 'A computer of yours';
    if (p.kind === 'machine') return 'NoClick machine';
    return p.kind === 'agent_sandbox' ? 'Cloud sandbox' : 'Developer sandbox';
}

/** Its size, where it's known: "2 vCPU · 4 GB". */
export const placeSize = (p: Place) => (isOwn(p) ? null : [p.cpu ? `${p.cpu} vCPU` : null, p.memoryGb ? `${p.memoryGb} GB` : null].filter(Boolean).join(' · ') || null);

/** Opens an agent where it runs, its session or its machine page, where Work is open (none from Resources). */
export function useOpenRun(): ((agentId: string, machine?: boolean) => void) | undefined {
    const nav = useContext(WorkNavContext);
    if (!nav) return undefined;
    return (agentId, machine = false) => (machine ? nav.openMachine(agentId) : nav.openAgent(agentId));
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
    return (
        <Surface className="px-4 py-1 sm:px-5">
            <dl className="divide-y divide-border dark:divide-foreground/[0.06]">
                {rows.map(([label, value]) => (
                    <div key={label} className="flex gap-4 py-2.5 text-[14px]">
                        <dt className="w-[132px] shrink-0 text-muted-foreground">{label}</dt>
                        <dd className="min-w-0 flex-1 text-foreground">{value}</dd>
                    </div>
                ))}
            </dl>
        </Surface>
    );
}

/** The one command that pairs a computer of yours, with a new one when it lapses. */
function Pairing({ computer }: { computer: OwnComputer }) {
    const client = useWorkClient();
    const [fresh, setFresh] = useState<OwnComputer | null>(null);
    const pairing = (fresh ?? computer).pairing;
    const renew = async () => {
        try {
            setFresh(await newPairing(client, computer.id));
            invalidateV1(OWN_KEY);
        } catch (error) {
            toast.error('Couldn’t get a new code', { description: error instanceof Error ? error.message : String(error) });
        }
    };
    return (
        <Section title="Pair it">
            <Surface className="px-4 py-4 sm:px-5">
                {pairing?.command ? (
                    <>
                        <p className="text-[14px]">Run this on the computer, once, within 30 minutes:</p>
                        <div className="mt-2 flex items-center gap-2 rounded-full bg-foreground/[0.05] py-1 pl-4 pr-1">
                            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{pairing.command}</code>
                            <CopyButton value={pairing.command} />
                        </div>
                    </>
                ) : (
                    <p className="text-[14px] text-muted-foreground">{pairing?.installingOn ? `It’s installing on ${pairing.installingOn}.` : 'Its pairing command was shown once, when it was added.'}</p>
                )}
                <button type="button" onClick={() => void renew()} className={cn(SMALL_SECONDARY, 'mt-3')}>
                    <RefreshCw className="h-3.5 w-3.5" strokeWidth={2} />
                    Get a new code
                </button>
            </Surface>
        </Section>
    );
}

/** A machine's page body: a NoClick machine and a computer of yours have the machine's own sections (its state and
 *  figures, what's on it, health, getting in, files and settings); a sandbox up now says what it is and who's on it. */
export function MachineBody({ place, now, onDeleted }: { place: Place; now: string; onDeleted?: () => void }) {
    if (isOwn(place) || place.kind === 'machine') {
        return (
            <div data-testid="machine-body" className="mt-6">
                <MachineDetail id={place.id} now={Date.parse(now)} own={isOwn(place) ? place : null} lead={false} onDeleted={onDeleted ?? (() => undefined)} between={<OwnNotes place={place} />} />
            </div>
        );
    }
    return <SandboxBody place={place} now={now} />;
}

/** What a computer of yours says before its sections: that agents don't run on machines here yet, and while it's
 *  still pairing, the one command that pairs it. */
export function OwnNotes({ place }: { place: Place }) {
    if (!isOwn(place)) return null;
    return (
        <>
            {place.agentsEnabled === false && (
                <div className="mt-8" data-testid="agents-not-enabled">
                    <Surface className="px-4 py-3.5 text-[14px] text-foreground/90 sm:px-5">{AGENTS_NOT_ENABLED}</Surface>
                </div>
            )}
            {place.status === 'provisioning' && <Pairing computer={place} />}
        </>
    );
}

/** An agent's sandbox or a developer sandbox, up now: what it is, what it costs while it runs, and who's on it. */
function SandboxBody({ place, now }: { place: Compute; now: string }) {
    const open = useOpenRun();
    const names = useAgentNames();
    // Each agent once: its one session runs there, whoever talks to it.
    const runs = [...new Map(place.running.map((r) => [r.agentId, r])).values()];
    const facts: [string, ReactNode][] = [
        ['State', placeState(place, now)],
        ['Kind', place.kind === 'agent_sandbox' ? 'The agent’s one sandbox, shared by everyone talking to it: NoClick starts it when the agent needs a shell and puts it to sleep after' : 'A developer sandbox your code started'],
        ...((placeSize(place) ? [['Size', placeSize(place)]] : []) as [string, string][]),
        ...((place.region ? [['Region', regionName(place.region)]] : []) as [string, string][]),
        ...((place.usdPerHour !== null ? [['Price', `${formatDollars(place.usdPerHour)} an hour while it runs`]] : []) as [string, string][]),
        ...((place.spentUsdToday !== null ? [['Today', `${formatDollars(place.spentUsdToday)} so far`]] : []) as [string, string][]),
    ];
    return (
        <div data-testid="machine-body">
            <Section title="Facts">
                <Facts rows={facts} />
            </Section>
            <Section title="What runs there" meta={runs.length || undefined}>
                {runs.length ? (
                    <Surface>
                        {runs.map((r) => (
                            <div key={r.agentId} className="group flex items-center gap-3 border-b border-border px-4 py-3 last:border-0 dark:border-foreground/[0.06]">
                                <AgentFace agent={{ id: r.agentId, name: names.get(r.agentId) ?? r.agentName }} size={28} />
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[14px] font-medium">{names.get(r.agentId) ?? r.agentName}</span>
                                    <span className="flex items-center gap-1.5 truncate text-[12.5px] text-muted-foreground">
                                        {r.harness && <HarnessMark harness={r.harness} className="h-3 w-3" />}
                                        {[r.harness ? harnessLabel(r.harness) : null, r.state].filter(Boolean).join(' · ')}
                                    </span>
                                </span>
                                {open && (
                                    <button
                                        type="button"
                                        aria-label={`Open ${names.get(r.agentId) ?? r.agentName}`}
                                        onClick={() => open(r.agentId)}
                                        className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground"
                                    >
                                        <ChevronRight className="h-4 w-4" />
                                    </button>
                                )}
                            </div>
                        ))}
                    </Surface>
                ) : (
                    <p className="text-[14px] text-muted-foreground">Nothing runs on it now.</p>
                )}
            </Section>
        </div>
    );
}
