// The facts every view of an agent can show: where it runs (a chip that opens its machine), its harness (with Change),
// its model and whose account pays (and, while a plan's limit has it on another, when it goes back), its access, its
// triggers in a line and its sessions. Read from the agent, its triggers, its sandbox and the account's model
// connections.
import { type ReactNode } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, Check, ChevronRight, Server } from 'lucide-react';
import { Agent, type PermissionMode } from 'noclick';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { nameOf } from '../agents/reads';
import { HARNESSES, HarnessMark, harnessLabel, harnessName } from '../agents/harness';
import { useHarnessSwitch } from '../agents/harnessSwitch';
import { accountPayer, accountTitle, NOCLICK_KEY_ACCOUNT } from '../newAgent/accounts';
import { switchedFromLine } from '../newAgent/switchWords';
import { AccountMark } from '../newAgent/ModelPicker';
import { modelName, modesOf, PERMISSION_ICON, PERMISSION_MODES, useHarnesses, useHarnessModels, useModelAccounts } from '../newAgent/catalog';
import { KindIcon } from '../triggers/data';
import { byAttention, nextRun, shortWhen, type TriggerItem } from '../triggers/model';
import { rereadAgent, useConversationSandbox, useMachine } from './reads';

// ── where it runs ───────────────────────────────────────────────────────────

/** Running is a live dot; asleep an empty ring. */
export function MachineDot({ running }: { running: boolean }) {
    return running ? (
        <span className="relative h-2 w-2 shrink-0">
            <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/50 motion-reduce:animate-none" />
            <span className="relative block h-2 w-2 rounded-full bg-emerald-500" />
        </span>
    ) : (
        <span className="h-2 w-2 shrink-0 rounded-full ring-[1.5px] ring-inset ring-foreground/40" />
    );
}

/** "4m", "2h", "12 days": how long it's been up. */
export function upFor(since: Date | null, now = Date.now()): string {
    if (!since) return '';
    const m = Math.max(0, Math.round((now - since.getTime()) / 60_000));
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    return h < 48 ? `${h}h` : `${Math.floor(h / 24)} days`;
}

/** Where it runs, as a pill that opens its machine: its sandbox (up or asleep), or its machine. `short`:
 *  its name and dot alone (a narrow header beside a title). */
export function MachineChip({ agent, conversation, onOpen, short }: { agent: Agent; conversation: string | null; onOpen: () => void; short?: boolean }) {
    const sandbox = useConversationSandbox(agent.id, conversation);
    const machine = useMachine(agent.machineId);
    const onMachine = !!agent.machineId;
    const running = onMachine ? machine.data?.status === 'running' : sandbox.data?.status === 'running';
    const name = onMachine ? (machine.data?.name ?? 'Machine') : 'Sandbox';
    const state = onMachine
        ? machine.data
            ? machine.data.status === 'running'
                ? 'Up'
                : // An own machine that stopped answering (the own-machine branch adds the status).
                  (machine.data.status as string) === 'offline'
                  ? 'Offline'
                  : 'Stopped'
            : ''
        : running
          ? `Running ${upFor(sandbox.data?.startedAt ?? null)}`
          : conversation
            ? 'Asleep'
            : 'Starts with its first turn';
    return (
        <ShortcutTooltip label="Open its machine: files, what's on it, your own shell">
            <button
                type="button"
                onClick={onOpen}
                className="inline-flex h-7 max-w-full items-center gap-2 rounded-full bg-foreground/[0.04] pl-2.5 pr-3 text-[12.5px] text-foreground/85 ring-1 ring-inset ring-foreground/[0.08] transition-colors hover:bg-foreground/[0.07] hover:text-foreground"
            >
                <Server className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.9} />
                <span className="shrink-0">{name}</span>
                <MachineDot running={running} />
                {!short && <span className="min-w-0 truncate tabular-nums text-muted-foreground">{state}</span>}
            </button>
        </ShortcutTooltip>
    );
}

// ── its harness ─────────────────────────────────────────────────────────────

/** Moving an agent to another harness, as its box's model picker does (agents/harnessSwitch): its conversation
 *  carries on there. Where several of your accounts run the harness, the menu asks which in place. */
export function HarnessMenu({ agent, className, children }: { agent: Agent; className?: string; children: ReactNode }) {
    const moves = useHarnessSwitch(agent);
    const choosing = moves.choosing;
    return (
        <>
            <DropdownMenu onOpenChange={(open) => !open && moves.cancel()}>
                <DropdownMenuTrigger disabled={!!moves.moving} className={cn('data-[state=open]:bg-foreground/[0.07] data-[state=open]:text-foreground', className)}>
                    {children}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" sideOffset={6} className="w-[320px] rounded-xl p-1">
                    {choosing ? (
                        <>
                            <DropdownMenuLabel className="flex items-center gap-1.5 px-2.5 pb-1 pt-1.5 text-[12px] font-normal leading-snug text-muted-foreground">
                                <HarnessMark harness={choosing.harness.name} className="h-3.5 w-3.5" />
                                Which of your accounts runs {harnessLabel(choosing.harness.name)}?
                            </DropdownMenuLabel>
                            {choosing.accounts.map((a) => (
                                <DropdownMenuItem key={a.id} onSelect={() => moves.choose(a.id)} className="items-start gap-2.5 rounded-lg px-2.5 py-2">
                                    <span className="grid h-5 w-4 shrink-0 place-items-center">
                                        <AccountMark account={a} className="h-4 w-4" />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="block text-[14px]">{accountTitle(a)}</span>
                                        <span className="block text-[12.5px] leading-snug text-muted-foreground">{a.note}</span>
                                    </span>
                                </DropdownMenuItem>
                            ))}
                            <DropdownMenuItem
                                onSelect={(e) => {
                                    e.preventDefault();
                                    moves.cancel();
                                }}
                                className="gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] text-muted-foreground"
                            >
                                <ArrowLeft className="h-4 w-4" strokeWidth={2} />
                                Another harness
                            </DropdownMenuItem>
                        </>
                    ) : (
                        <>
                            <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-[12px] font-normal leading-snug text-muted-foreground">
                                Move {nameOf(agent)} to another harness. Its session carries on there from its next turn.
                            </DropdownMenuLabel>
                            {HARNESSES.map((h) => (
                                <DropdownMenuItem
                                    key={h.id}
                                    onSelect={(e) => {
                                        if (h.id === agent.harness) return;
                                        // A choice of account keeps the menu open, asking which.
                                        if (moves.start({ harness: h.id }) === 'choose') e.preventDefault();
                                    }}
                                    className="items-start gap-2.5 rounded-lg px-2.5 py-2"
                                >
                                    <span className="grid h-5 w-4 shrink-0 place-items-center">
                                        <HarnessMark harness={h.id} className="h-4 w-4" />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="block text-[14px]">{harnessName(h.id)}</span>
                                        <span className="block text-[12.5px] leading-snug text-muted-foreground">{h.note}</span>
                                    </span>
                                    <Check className={cn('mt-0.5 h-4 w-4 shrink-0', h.id === agent.harness ? 'opacity-100' : 'opacity-0')} strokeWidth={2} />
                                </DropdownMenuItem>
                            ))}
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            {moves.dialog}
        </>
    );
}

/** How new sessions start: its default mode, changed in place. A session set its own way keeps it. NoClick's
 *  own runtime takes no mode: the account's policy on its tools holds its calls for a person. */
export function PermissionsMenu({ agent }: { agent: Agent }) {
    const client = useWorkClient();
    const harnesses = useHarnesses();
    const harness = harnesses.data?.find((h) => h.name === (agent.harness ?? 'sdk'));
    const { modes, note } = modesOf(harness);
    const current = PERMISSION_MODES.find((m) => m.id === agent.permissionMode) ?? PERMISSION_MODES[3];
    const Icon = PERMISSION_ICON[current.id];
    const pick = async (mode: PermissionMode) => {
        if (mode === agent.permissionMode) return;
        try {
            await Agent.fromId(agent.id, { client }).update({ permissionMode: mode });
            rereadAgent(agent.id);
        } catch (error) {
            toast('Couldn’t change how it asks', { description: error instanceof Error ? error.message : String(error) });
        }
    };
    if (harness && !modes.length) return <span className="text-foreground/85">Its tools’ policy</span>;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={`Permissions for new sessions: ${current.label}`}
                className="-my-0.5 -ml-1.5 inline-flex items-center gap-1.5 rounded-full px-1.5 py-0.5 transition-colors hover:bg-foreground/[0.06] data-[state=open]:bg-foreground/[0.07]"
            >
                <Icon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                {current.label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={6} className="w-[300px] rounded-xl p-1">
                <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-[12px] font-normal leading-snug text-muted-foreground">
                    How {nameOf(agent)}’s new sessions start. One you’ve set its own way keeps it.{note && ` ${note}`}
                </DropdownMenuLabel>
                {modes.map((m) => {
                    const ModeIcon = PERMISSION_ICON[m.id];
                    return (
                        <DropdownMenuItem key={m.id} onSelect={() => void pick(m.id)} className="items-start gap-2.5 rounded-lg px-2.5 py-2">
                            <ModeIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                            <span className="min-w-0 flex-1">
                                <span className="block text-[14px]">{m.label}</span>
                                <span className="block text-[12.5px] leading-snug text-muted-foreground">{m.note}</span>
                            </span>
                            <Check className={cn('mt-0.5 h-4 w-4 shrink-0', m.id === current.id ? 'opacity-100' : 'opacity-0')} strokeWidth={2} />
                        </DropdownMenuItem>
                    );
                })}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/** Its model by its plain name, and who pays: "Sonnet 5.5 · your Claude plan". */
export function useModelLine(agent: Agent): { model: string; payer: string } {
    const harnesses = useHarnesses();
    const harness = harnesses.data?.find((h) => h.name === (agent.harness ?? 'sdk'));
    const models = useHarnessModels(harness);
    const { accounts } = useModelAccounts();
    const id = agent.model ?? harness?.defaultModel ?? '';
    const model = id ? modelName(models.data?.find((m) => m.id === id)?.label, id) : '';
    const connection = agent.modelConnection;
    const account = connection ? (connection === NOCLICK_KEY_ACCOUNT.id ? NOCLICK_KEY_ACCOUNT : accounts?.find((a) => a.id === connection)) : NOCLICK_KEY_ACCOUNT;
    return { model, payer: account ? accountPayer(account) : connection ? `the connection ${connection}` : '' };
}

/** While a plan's limit has it on another connection, when it goes back: "On your personal Claude plan until 3:20 PM,
 *  then back on your work Claude plan". */
export function SwitchedFrom({ agent }: { agent: Agent }) {
    const { accounts } = useModelAccounts();
    const from = agent.switchedFrom;
    // Said once the accounts are read, so it names them.
    if (!from || !accounts) return null;
    const line = switchedFromLine({ current: agent.modelConnection ?? null, home: from.connection, homeName: from.name, resetsAt: from.resetsAt ? new Date(from.resetsAt) : null }, accounts);
    return (
        <span className="block pt-0.5 text-[12.5px] leading-snug text-muted-foreground" data-testid="switched-from">
            {line}
        </span>
    );
}

/** Where it runs, the harness, the model and who pays, its triggers in a line (opening its Triggers tab) and its
 *  sessions (`sessions`, opening the earlier ones to resume). */
export function AgentFacts({
    agent,
    conversation,
    triggers,
    onMachine,
    onTriggers,
    sessions,
}: {
    agent: Agent;
    /** Its session. */
    conversation: string | null;
    /** Its triggers as Work shows them; undefined while they're read, null when they couldn't be. */
    triggers: readonly TriggerItem[] | null | undefined;
    onMachine: () => void;
    onTriggers: () => void;
    sessions?: ReactNode;
}) {
    const harnesses = useHarnesses();
    const harness = agent.harness ?? 'sdk';
    const version = harnesses.data?.find((h) => h.name === harness)?.version;
    const { model, payer } = useModelLine(agent);
    const stopped = (triggers ?? []).filter((t) => t.state === 'stopped').length;
    const next = nextRun(triggers ?? []);
    const row = (label: string, body: ReactNode) => (
        <div className="flex gap-3">
            <dt className="w-[70px] shrink-0 pt-[5px] text-[12.5px] text-muted-foreground">{label}</dt>
            <dd className="min-w-0 flex-1 text-[13.5px] leading-snug">{body}</dd>
        </div>
    );
    return (
        <dl className="space-y-2.5" data-testid="agent-facts">
            {row('Runs on', <MachineChip agent={agent} conversation={conversation} onOpen={onMachine} />)}
            {row(
                'Harness',
                <span className="flex items-center gap-1.5 pt-[4px]">
                    <HarnessMark harness={harness} className="h-3.5 w-3.5" />
                    {harnessName(harness)}
                    {version && <span className="text-muted-foreground">{version}</span>}
                    <HarnessMenu agent={agent} className="-my-1 ml-auto rounded-full px-1.5 py-0.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                        Change
                    </HarnessMenu>
                </span>
            )}
            {row(
                'Model',
                <span className="block pt-[4px]">
                    {model} {payer && <span className="text-muted-foreground">· {payer}</span>}
                    <SwitchedFrom agent={agent} />
                </span>
            )}
            {row('Access', <span className="block pt-[4px]"><PermissionsMenu agent={agent} /></span>)}
            {row(
                'Triggers',
                <button type="button" onClick={onTriggers} data-testid="triggers-fact" className="-mx-1.5 flex min-w-0 max-w-full items-center gap-2 rounded-full px-1.5 py-[3px] text-left transition-colors hover:bg-foreground/[0.05]">
                    {triggers === undefined ? (
                        <span className="text-muted-foreground">…</span>
                    ) : triggers === null ? (
                        <span className="text-muted-foreground">Couldn’t read them</span>
                    ) : !triggers.length ? (
                        <span className="text-muted-foreground">Only when messaged</span>
                    ) : (
                        <>
                            <span className="flex shrink-0 items-center gap-1">
                                {byAttention(triggers)
                                    .slice(0, 4)
                                    .map((t) => (
                                        <KindIcon key={t.id} item={t} className="h-3.5 w-3.5" />
                                    ))}
                            </span>
                            <span className="min-w-0 truncate">
                                {triggers.length === 1 ? '1 trigger' : `${triggers.length} triggers`}
                                {stopped > 0 && <span className="text-red-600 dark:text-red-400"> · {stopped} stopped</span>}
                                {/* What stopped comes before when it next runs, as the footer's chip says it. */}
                                {!stopped && next && <span className="text-muted-foreground"> · next {shortWhen(next.at)}</span>}
                            </span>
                        </>
                    )}
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                </button>
            )}
            {sessions && row('Sessions', sessions)}
        </dl>
    );
}
