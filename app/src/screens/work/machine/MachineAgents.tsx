// What's on a machine: a row of slots that reads "1 of 2 working" at a glance, then each agent and what it's doing,
// with Move an agent here and a menu on each row to move it off (to its own cloud sandbox, or another machine). A move
// is the agent's own `machine` change: it lands on its next turn and brings its files.
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
    Box,
    ChevronRight,
    Laptop,
    MoreHorizontal,
    Plus,
    Server,
} from 'lucide-react';
import { Agent, type Machine } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { Section, Surface } from '@/screens/resources/ui';
import { ShellDialog } from '@/ui/ShellDialog';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import {
    AGENTS_KEY,
    nameOf,
    useAgents,
    useSpaceNoClicks,
} from '../agents/reads';
import { useWorkClient } from '../client';
import { AgentFace } from '../resources/knowledge/parts';
import {
    answerNotes,
    canWork,
    isUp,
    slotsOf,
    workingIds,
    type MachineView,
} from './machineView';
import { rereadMachine, useMachines } from './reads';

const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);
const MENU_ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';

interface OnIt {
    id: string;
    name: string;
    line: string;
    working: boolean;
}

/** What each agent on it is doing: working in a slot, waiting its turn, waiting for the machine, or idle. */
export function agentLines(
    view: MachineView,
    agents: { id: string; name: string }[]
): OnIt[] {
    const slots = slotsOf(view) ?? Infinity;
    const working = workingIds(view);
    return agents.map((a) => {
        const at = working.indexOf(a.id);
        const line =
            at >= 0 && at < slots
                ? 'Working now'
                : at >= slots
                  ? 'Waiting its turn: every slot is busy'
                  : !canWork(view)
                    ? view.status === 'offline'
                        ? 'Waiting for it to come back'
                        : 'Waiting for it to run'
                    : 'Idle';
        return { id: a.id, name: a.name, line, working: at >= 0 && at < slots };
    });
}

/** Where an agent can go instead: its own cloud sandbox, or another machine it may run on. */
function destinations(
    view: MachineView,
    machines: readonly Machine[],
    agent: Agent
): { id: string | null; name: string; own: boolean }[] {
    const others = machines.filter(
        (m) =>
            m.id !== view.id &&
            m.status !== 'failed' &&
            (m.kind !== 'own' || agent.userId === null)
    );
    return [
        { id: null, name: 'its own cloud sandbox', own: false },
        ...others.map((m) => ({
            id: m.id,
            name: m.name,
            own: m.kind === 'own',
        })),
    ];
}

export function MachineAgents({ view }: { view: MachineView }) {
    const client = useWorkClient();
    const agents = useAgents();
    const noclicks = useSpaceNoClicks();
    const machines = useMachines().data ?? [];
    const [moving, setMoving] = useState(false);
    const all = useMemo(() => agents.data ?? [], [agents.data]);
    const here = useMemo(
        () => all.filter((a) => a.machineId === view.id),
        [all, view.id]
    );
    const named = (a: Agent) => nameOf(a, noclicks);
    const rows = agentLines(
        view,
        here.map((a) => ({ id: a.id, name: named(a) }))
    );
    const slots = slotsOf(view);
    const shown = rows.filter((r) => r.working);
    const waiting = workingIds(view).length - shown.length;

    const move = async (
        agent: Agent,
        to: { id: string | null; name: string }
    ) => {
        try {
            const moved = await Agent.fromId(agent.id, {
                client,
                user: agent.userId,
            }).update({ machine: to.id });
            toast(
                `${named(agent)} moves to ${to.id === null ? 'its own cloud sandbox' : to.name}`,
                {
                    description: [
                        'On its next turn, with its files.',
                        ...answerNotes(moved.raw),
                    ].join(' '),
                }
            );
        } catch (error) {
            toast(`Couldn’t move ${named(agent)}`, {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            invalidateV1(AGENTS_KEY);
            rereadMachine(view.id);
            if (to.id) rereadMachine(to.id);
        }
    };

    return (
        <Section
            title="On it"
            meta={`${here.length} ${here.length === 1 ? 'agent' : 'agents'}`}
            action={
                <button
                    type="button"
                    onClick={() => setMoving(true)}
                    className={SMALL_SECONDARY}
                >
                    <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                    Move an agent here
                </button>
            }
        >
            {here.length ? (
                <>
                    {slots ? (
                        <div
                            className="mb-3 flex flex-wrap items-center gap-3 text-[13.5px]"
                            data-testid="machine-slots"
                        >
                            <span aria-hidden className="flex flex-wrap gap-1">
                                {Array.from(
                                    { length: Math.min(slots, 16) },
                                    (_, i) => (
                                        <span
                                            key={i}
                                            className={cn(
                                                'grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold',
                                                shown[i]
                                                    ? 'bg-foreground text-background'
                                                    : 'ring-1 ring-inset ring-foreground/20'
                                            )}
                                        >
                                            {shown[i]?.name.charAt(0) ?? ''}
                                        </span>
                                    )
                                )}
                            </span>
                            <span>
                                <span className="font-semibold tabular-nums">
                                    {shown.length} of {slots}
                                </span>{' '}
                                working now
                                {waiting > 0 ? ` · ${waiting} waiting` : ''}
                            </span>
                        </div>
                    ) : null}
                    <Surface>
                        {here.map((agent, i) => (
                            <div
                                key={agent.id}
                                className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-0 dark:border-foreground/[0.06]"
                            >
                                <AgentFace
                                    agent={{ id: agent.id, name: named(agent) }}
                                    size={28}
                                />
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[14px] font-medium">
                                        {named(agent)}
                                    </span>
                                    <span
                                        className={cn(
                                            'block truncate text-[12.5px]',
                                            rows[i].working
                                                ? 'text-emerald-600 dark:text-emerald-400'
                                                : 'text-muted-foreground'
                                        )}
                                    >
                                        {rows[i].line}
                                    </span>
                                </span>
                                <DropdownMenu>
                                    <DropdownMenuTrigger
                                        aria-label={`More for ${named(agent)}`}
                                        className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground max-md:h-10 max-md:w-10"
                                    >
                                        <MoreHorizontal className="h-4 w-4" />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent
                                        align="end"
                                        sideOffset={4}
                                        className="min-w-[240px] rounded-xl p-1"
                                    >
                                        {destinations(
                                            view,
                                            machines,
                                            agent
                                        ).map((d) => (
                                            <DropdownMenuItem
                                                key={d.id ?? 'sandbox'}
                                                onSelect={() =>
                                                    void move(agent, d)
                                                }
                                                className={MENU_ITEM}
                                            >
                                                {d.id === null ? (
                                                    <Box
                                                        className="h-4 w-4 text-muted-foreground"
                                                        strokeWidth={1.75}
                                                    />
                                                ) : d.own ? (
                                                    <Laptop
                                                        className="h-4 w-4 text-muted-foreground"
                                                        strokeWidth={1.75}
                                                    />
                                                ) : (
                                                    <Server
                                                        className="h-4 w-4 text-muted-foreground"
                                                        strokeWidth={1.75}
                                                    />
                                                )}
                                                <span className="grid">
                                                    <span>
                                                        Move to {d.name}
                                                    </span>
                                                    <span className="text-[12px] text-muted-foreground">
                                                        On its next turn, with
                                                        its files
                                                    </span>
                                                </span>
                                            </DropdownMenuItem>
                                        ))}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </div>
                        ))}
                    </Surface>
                    {slots ? (
                        <p className="mt-2 text-[12.5px] text-muted-foreground">
                            When every slot is busy, the next agent waits its
                            turn.
                        </p>
                    ) : null}
                </>
            ) : (
                <Surface className="px-4 py-3.5 sm:px-5">
                    <p className="text-[14px] text-muted-foreground">
                        No agents on it yet.{' '}
                        <button
                            type="button"
                            onClick={() => setMoving(true)}
                            className="font-medium text-foreground underline decoration-foreground/30 underline-offset-[3px] hover:decoration-foreground"
                        >
                            Move one here
                        </button>
                        ; it brings its files.
                    </p>
                </Surface>
            )}
            {moving && (
                <MoveHere
                    view={view}
                    candidates={all.filter(
                        (a) =>
                            a.machineId !== view.id &&
                            !!a.harness &&
                            a.harness !== 'sdk' &&
                            (view.kind !== 'own' || a.userId === null)
                    )}
                    machines={machines}
                    named={named}
                    onPick={(agent) => {
                        setMoving(false);
                        void move(agent, { id: view.id, name: view.name });
                        if (
                            isUp(view) &&
                            workingIds(view).length >= (slots ?? Infinity)
                        )
                            toast('Every slot is busy now', {
                                description: `${named(agent)} may wait its turn.`,
                            });
                    }}
                    onClose={() => setMoving(false)}
                />
            )}
        </Section>
    );
}

function MoveHere({
    view,
    candidates,
    machines,
    named,
    onPick,
    onClose,
}: {
    view: MachineView;
    candidates: Agent[];
    machines: readonly Machine[];
    named: (a: Agent) => string;
    onPick: (agent: Agent) => void;
    onClose: () => void;
}) {
    const where = (a: Agent) =>
        a.machineId
            ? (machines.find((m) => m.id === a.machineId)?.name ??
              'Another machine')
            : 'Cloud sandbox';
    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && onClose()}
            title={`Move an agent to ${view.name}`}
            description="It moves on its next turn and brings its files."
            mark={<Plus className="h-5 w-5" strokeWidth={1.75} />}
            testId="move-agent-here"
        >
            {candidates.length ? (
                <div className="grid gap-1.5 pb-2">
                    {candidates.map((a) => (
                        <button
                            key={a.id}
                            type="button"
                            onClick={() => onPick(a)}
                            className="flex w-full items-center gap-3 rounded-[20px] px-3.5 py-3 text-left ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.1]"
                        >
                            <AgentFace
                                agent={{ id: a.id, name: named(a) }}
                                size={32}
                            />
                            <span className="grid min-w-0 flex-1">
                                <span className="truncate text-[14px] font-medium">
                                    {named(a)}
                                </span>
                                <span className="truncate text-[12.5px] text-muted-foreground">
                                    {where(a)} now
                                </span>
                            </span>
                            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                        </button>
                    ))}
                </div>
            ) : (
                <p className="pb-4 text-[13.5px] text-muted-foreground">
                    Every coding agent that can run here is on it already.
                </p>
            )}
        </ShellDialog>
    );
}
