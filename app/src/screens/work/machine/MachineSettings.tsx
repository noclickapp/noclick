// A machine's settings in four plain groups: Settings (its name, its size, and on your own computer what NoClick uses
// of it and whether agents run apps and test databases), Power (stop, start, restart; your own you switch on and off
// yourself), Advanced (its public web addresses and the most it may cost a month), and Delete, which says exactly what
// goes and moves its agents back to their own cloud sandboxes. Sizes are priced a month and a day, as machines are.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import {
    ChevronDown,
    Pencil,
    Power,
    RotateCcw,
    Server,
    Trash2,
} from 'lucide-react';
import {
    Machine,
    type AppTesting,
    type MachineSizeName,
} from 'noclick';
import type { OwnComputer } from '@/screens/resources/knowledge';
import {
    BUTTON_DANGER,
    BUTTON_GHOST,
    BUTTON_PRIMARY,
    BUTTON_SECONDARY,
} from '@/ui/buttons';
import { PILL_FIELD } from '@/ui/fields';
import { Section, Surface } from '@/screens/resources/ui';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { nameOf, useAgents, useSpaceNoClicks } from '../agents/reads';
import { useWorkClient } from '../client';
import { powerAction } from './machineApi';
import {
    andList,
    dayPrice,
    isUp,
    ownDevice,
    perDay,
    perMonth,
    placeName,
    SIZE_LABELS,
    type MachineView,
} from './machineView';
import { HOST_NAMES } from './offers';
import { rereadMachine, OWN_KEY, useMachineSizes } from './reads';
import { ShareChoice } from './ShareChoice';
import { invalidateV1 } from '@/sdk/useV1';

const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);
const SMALL_DANGER = BUTTON_DANGER.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);
const usd = (n: number) => `$${n.toFixed(2)}`;
/** What a move to a smaller disk leaves free (the platform's headroom). */
const MOVE_HEADROOM = 0.9;

/** Your own computer's say on apps and test databases, as Ask first / Yes / No. */
export const APP_TESTING_CHOICES: readonly [AppTesting, string][] = [
    ['ask_first', 'Ask first'],
    ['by_itself', 'Yes'],
    ['never', 'No'],
];
const APP_TESTING_SAID: Record<AppTesting, string> = {
    ask_first:
        'Each agent asks you in its chat before it starts an app or a test database, in its own sealed container.',
    by_itself:
        'Each agent starts apps and test databases (Docker) in its own sealed container when a task needs them; this computer’s own stay untouched.',
    never: 'Agents can run code and scripts, but not full apps or test databases.',
};

function Row({
    title,
    line,
    children,
    danger,
}: {
    title: ReactNode;
    line?: ReactNode;
    children?: ReactNode;
    danger?: boolean;
}) {
    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-3.5 last:border-0 sm:px-5 dark:border-foreground/[0.06]">
            <div className="min-w-0 flex-1">
                <p
                    className={cn(
                        'text-[14px] font-medium',
                        danger && 'text-red-600 dark:text-red-400'
                    )}
                >
                    {title}
                </p>
                {line && (
                    <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">
                        {line}
                    </p>
                )}
            </div>
            {children && (
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {children}
                </div>
            )}
        </div>
    );
}

/** The agents on it, by name, as the list reads them. */
function useAgentsOn(machineId: string): string[] {
    const agents = useAgents().data ?? [];
    const noclicks = useSpaceNoClicks();
    return agents
        .filter((a) => a.machineId === machineId)
        .map((a) => nameOf(a, noclicks));
}

export function MachineSettings({
    view,
    own,
    onDeleted,
    onResize,
}: {
    view: MachineView;
    own: OwnComputer | null;
    onDeleted: () => void;
    onResize: () => void;
}) {
    const client = useWorkClient();
    const machine = Machine.fromId(view.id, { client, user: view.userId });
    const [renaming, setRenaming] = useState<string | null>(null);
    const nameField = useRef<HTMLInputElement>(null);
    const askingName = renaming !== null;
    useEffect(() => {
        if (askingName) nameField.current?.select();
    }, [askingName]);
    const [advanced, setAdvanced] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [testing, setTesting] = useState<AppTesting | null>(null);
    const onIt = useAgentsOn(view.id);
    const noclick = view.kind === 'noclick';
    const canResize = view.status === 'running' || view.status === 'stopped';

    const rename = async () => {
        const name = renaming?.trim();
        if (!name || name === view.name) return setRenaming(null);
        try {
            await machine.update({ name });
            setRenaming(null);
        } catch (error) {
            toast('Couldn’t rename it', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            rereadMachine(view.id);
        }
    };
    // As the agent profile's App testing does: the PATCH says when loosening it waits for the owner's approval.
    const pickTesting = async (next: AppTesting) => {
        if (next === (testing ?? view.appTesting)) return;
        setTesting(next);
        try {
            await machine.update({ appTesting: next });
            rereadMachine(view.id);
        } catch (error) {
            toast('Couldn’t change app testing', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            setTesting(null);
        }
    };
    const testingNow = testing ?? view.appTesting;

    return (
        <>
            <Section title="Settings">
                <Surface>
                    {renaming !== null ? (
                        <form
                            className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 sm:px-5 dark:border-foreground/[0.06]"
                            onSubmit={(e) => {
                                e.preventDefault();
                                void rename();
                            }}
                        >
                            <input
                                ref={nameField}
                                aria-label="Name"
                                value={renaming}
                                onChange={(e) => setRenaming(e.target.value)}
                                maxLength={100}
                                className={cn(PILL_FIELD, 'min-w-0 flex-1')}
                            />
                            <button
                                type="submit"
                                className={cn(BUTTON_PRIMARY, 'h-8')}
                            >
                                Save
                            </button>
                            <button
                                type="button"
                                onClick={() => setRenaming(null)}
                                className={cn(BUTTON_GHOST, 'h-8')}
                            >
                                Cancel
                            </button>
                        </form>
                    ) : (
                        <Row title="Name" line={view.name}>
                            <button
                                type="button"
                                onClick={() => setRenaming(view.name)}
                                className={SMALL_SECONDARY}
                            >
                                <Pencil
                                    className="h-3.5 w-3.5"
                                    strokeWidth={2}
                                />
                                Rename
                            </button>
                        </Row>
                    )}
                    {noclick && view.size && (
                        <Row
                            title="Size"
                            line={[
                                SIZE_LABELS[view.size],
                                view.conversationsAtOnce
                                    ? `up to ${view.conversationsAtOnce} agents at once`
                                    : null,
                                view.monthlyUsd !== null
                                    ? perMonth(view.monthlyUsd)
                                    : null,
                            ]
                                .filter(Boolean)
                                .join(' · ')}
                        >
                            <button
                                type="button"
                                disabled={!canResize}
                                onClick={onResize}
                                className={SMALL_SECONDARY}
                            >
                                Change
                            </button>
                        </Row>
                    )}
                    {!noclick && own && (
                        <div className="border-b border-border px-4 py-1 sm:px-5 dark:border-foreground/[0.06]">
                            <ShareChoice
                                computer={own}
                                onSaved={() => invalidateV1(OWN_KEY)}
                            />
                        </div>
                    )}
                    {!noclick && view.appTesting && testingNow && (
                        <Row
                            title="Let agents run apps and test databases"
                            line={APP_TESTING_SAID[testingNow]}
                        >
                            <div
                                role="radiogroup"
                                aria-label="Let agents run apps and test databases"
                                className="inline-flex rounded-full bg-foreground/[0.06] p-0.5"
                            >
                                {APP_TESTING_CHOICES.map(([value, label]) => (
                                    <button
                                        key={value}
                                        type="button"
                                        role="radio"
                                        aria-checked={testingNow === value}
                                        disabled={testing !== null}
                                        onClick={() => void pickTesting(value)}
                                        className={cn(
                                            'h-7 whitespace-nowrap rounded-full px-3 text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait',
                                            testingNow === value
                                                ? 'bg-popover font-medium text-foreground shadow-sm ring-1 ring-inset ring-border dark:ring-foreground/[0.12]'
                                                : 'text-muted-foreground hover:text-foreground'
                                        )}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                        </Row>
                    )}
                </Surface>
            </Section>
            <Section title="Power">
                <Surface>
                    {noclick ? (
                        <>
                            <Row
                                title={
                                    view.status === 'stopped'
                                        ? 'Start it'
                                        : 'Stop it'
                                }
                                line={
                                    view.status === 'stopped'
                                        ? 'Agents can work on it again in about 3 minutes.'
                                        : `Agents pause until you start it again. Still charged ${view.monthlyUsd !== null ? perDay(view.monthlyUsd) : 'each day'}.`
                                }
                            >
                                <button
                                    type="button"
                                    disabled={
                                        !(
                                            view.status === 'stopped' ||
                                            isUp(view)
                                        )
                                    }
                                    onClick={() =>
                                        void powerAction(
                                            client,
                                            view,
                                            view.status === 'stopped'
                                                ? 'start'
                                                : 'stop'
                                        )
                                    }
                                    className={SMALL_SECONDARY}
                                >
                                    <Power
                                        className="h-3.5 w-3.5"
                                        strokeWidth={2}
                                    />
                                    {view.status === 'stopped'
                                        ? 'Start'
                                        : 'Stop'}
                                </button>
                            </Row>
                            <Row
                                title="Restart it"
                                line="Ends what agents are doing right now, then starts fresh. They pick up with their next message."
                            >
                                <button
                                    type="button"
                                    disabled={
                                        !(
                                            isUp(view) ||
                                            view.status === 'failed'
                                        )
                                    }
                                    onClick={() =>
                                        void powerAction(
                                            client,
                                            view,
                                            'restart'
                                        )
                                    }
                                    className={SMALL_SECONDARY}
                                >
                                    <RotateCcw
                                        className="h-3.5 w-3.5"
                                        strokeWidth={2}
                                    />
                                    Restart
                                </button>
                            </Row>
                        </>
                    ) : (
                        <Row
                            title="On and off"
                            line={`It works while your ${ownDevice(view.os).what} is on. Turn it off and on the way you always do; agents wait while it’s off.`}
                        />
                    )}
                </Surface>
            </Section>
            {noclick && (
                <>
                    <button
                        type="button"
                        aria-expanded={advanced}
                        onClick={() => setAdvanced(!advanced)}
                        className="-ml-3 mt-6 inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                    >
                        Advanced
                        <ChevronDown
                            className={cn(
                                'h-4 w-4 transition-transform',
                                advanced && 'rotate-180'
                            )}
                        />
                    </button>
                    {advanced && <Advanced view={view} />}
                </>
            )}
            <Surface className="mt-8 border-red-600/25 dark:border-red-400/25">
                <Row
                    danger
                    title={`${noclick ? 'Delete' : 'Remove'} ${view.name}`}
                    line={
                        noclick
                            ? `Its disk goes with it.${onIt.length ? ` ${andList(onIt)} ${onIt.length === 1 ? 'moves back to its own cloud sandbox' : 'move back to their own cloud sandboxes'}.` : ''}`
                            : 'NoClick uninstalls itself from it the next time it’s on. Your own files on it stay.'
                    }
                >
                    <button
                        type="button"
                        onClick={() => setDeleting(true)}
                        className={SMALL_DANGER}
                    >
                        {noclick ? 'Delete…' : 'Remove…'}
                    </button>
                </Row>
            </Surface>
            {deleting && (
                <DeleteDialog
                    view={view}
                    onIt={onIt}
                    onClose={() => setDeleting(false)}
                    onDeleted={onDeleted}
                />
            )}
        </>
    );
}

/** Its public web addresses, and the most it may cost a month. */
function Advanced({ view }: { view: MachineView }) {
    const client = useWorkClient();
    const machine = Machine.fromId(view.id, { client, user: view.userId });
    const [port, setPort] = useState('');
    const [open, setOpen] = useState(true);
    const [busy, setBusy] = useState(false);
    const add = async () => {
        const n = Number.parseInt(port, 10);
        if (!n || n < 1 || n > 65535)
            return toast('Pick a port first', {
                description:
                    'The number the app listens on, like 3000 or 8080.',
            });
        setBusy(true);
        try {
            const made = await machine.expose(n, { public: open });
            setPort('');
            toast(`Port ${n} has an address`, {
                description: `${made.url}${open ? '' : ', for requests with your API key'}.`,
            });
        } catch (error) {
            toast('Couldn’t give it an address', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            setBusy(false);
            rereadMachine(view.id);
        }
    };
    const close = async (n: number) => {
        try {
            await machine.closePort(n);
        } catch (error) {
            toast('Couldn’t close it', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            rereadMachine(view.id);
        }
    };
    return (
        <div data-testid="machine-advanced">
            <Section title="Public web addresses" className="mt-4">
                <p className="-mt-1 mb-3 text-[13.5px] text-muted-foreground">
                    Something running on it, like an app on port 3000, can get
                    its own address on the web.
                </p>
                <Surface>
                    {view.ports.map((p) => (
                        <div
                            key={p.port}
                            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-3 sm:px-5 dark:border-foreground/[0.06]"
                        >
                            <span className="text-[14px] font-medium">
                                Port {p.port}
                            </span>
                            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground/85">
                                {p.url}
                            </code>
                            <span className="text-[12.5px] text-muted-foreground">
                                {p.public
                                    ? 'Anyone can open it'
                                    : 'Needs your API key'}
                            </span>
                            <button
                                type="button"
                                onClick={() => void close(p.port)}
                                className={cn(
                                    BUTTON_GHOST,
                                    'h-7 px-2.5 text-[12.5px]'
                                )}
                            >
                                Close
                            </button>
                        </div>
                    ))}
                    <div className="flex flex-wrap items-center gap-2 px-4 py-3 sm:px-5">
                        <input
                            type="number"
                            inputMode="numeric"
                            min={1}
                            max={65535}
                            placeholder="Port"
                            aria-label="Port"
                            value={port}
                            onChange={(e) => setPort(e.target.value)}
                            className={cn(PILL_FIELD, 'h-8 w-24')}
                        />
                        <div
                            role="group"
                            aria-label="Who can open it"
                            className="inline-flex rounded-full bg-foreground/[0.06] p-0.5"
                        >
                            {[
                                [true, 'Anyone'],
                                [false, 'Only with your API key'],
                            ].map(([value, label]) => (
                                <button
                                    key={String(value)}
                                    type="button"
                                    aria-pressed={open === value}
                                    onClick={() => setOpen(value as boolean)}
                                    className={cn(
                                        'h-7 whitespace-nowrap rounded-full px-3 text-[12.5px] transition-colors',
                                        open === value
                                            ? 'bg-popover font-medium text-foreground shadow-sm ring-1 ring-inset ring-border dark:ring-foreground/[0.12]'
                                            : 'text-muted-foreground hover:text-foreground'
                                    )}
                                >
                                    {label as string}
                                </button>
                            ))}
                        </div>
                        <button
                            type="button"
                            disabled={busy || !isUp(view)}
                            onClick={() => void add()}
                            className={SMALL_SECONDARY}
                        >
                            Give it an address
                        </button>
                    </div>
                </Surface>
            </Section>
            {view.maxMonthlyUsd !== null && (
                <Surface className="mt-3">
                    <Row
                        title="Most it may cost a month"
                        line={`${usd(view.maxMonthlyUsd)}. A size above it is refused, so a change can never surprise you.`}
                    />
                </Surface>
            )}
        </div>
    );
}

interface SizeOption {
    size: MachineSizeName;
    cpu: number;
    memoryGb: number;
    atOnce: number;
    diskGb: number;
    usd: number;
    now: boolean;
    move: boolean;
}

/** The sizes it can be: what its host sells in its region, a smaller disk only where what it holds fits. */
export function resizeOptions(
    view: MachineView,
    sizes: readonly {
        name: MachineSizeName;
        cpu: number;
        memoryGb: number;
        workingConversations: number;
        hosts: {
            host: string;
            regions: string[];
            diskGb: number;
            monthlyUsd: number;
        }[];
    }[]
): SizeOption[] {
    const used = view.health?.diskUsedGb ?? 0;
    return sizes.flatMap((s): SizeOption[] => {
        if (s.name === view.size)
            return [
                {
                    size: s.name,
                    cpu: s.cpu,
                    memoryGb: s.memoryGb,
                    atOnce: s.workingConversations,
                    diskGb: view.diskGb ?? 0,
                    usd: view.monthlyUsd ?? 0,
                    now: true,
                    move: false,
                },
            ];
        const there = s.hosts.find(
            (h) =>
                h.host === view.host &&
                (!view.region || h.regions.includes(view.region))
        );
        if (!there) return [];
        const move = there.diskGb < (view.diskGb ?? 0);
        if (move && used > there.diskGb * MOVE_HEADROOM) return [];
        return [
            {
                size: s.name,
                cpu: s.cpu,
                memoryGb: s.memoryGb,
                atOnce: s.workingConversations,
                diskGb: there.diskGb,
                usd: there.monthlyUsd,
                now: false,
                move,
            },
        ];
    });
}

export function ResizeDialog({
    view,
    onClose,
}: {
    view: MachineView;
    onClose: () => void;
}) {
    const client = useWorkClient();
    const sizes = useMachineSizes();
    const options = useMemo(
        () => resizeOptions(view, sizes.data ?? []),
        [view, sizes.data]
    );
    const [pick, setPick] = useState<MachineSizeName | null>(null);
    const [busy, setBusy] = useState(false);
    const current = options.find((o) => o.now);
    const chosen = options.find((o) => o.size === pick) ?? current;
    const go = async () => {
        if (!chosen || chosen.now) return;
        setBusy(true);
        try {
            // The price was read here: a ceiling under it rises to it.
            await Machine.fromId(view.id, { client, user: view.userId }).update(
                {
                    size: chosen.size,
                    maxMonthlyUsd: Math.max(
                        view.maxMonthlyUsd ?? 0,
                        chosen.usd
                    ),
                }
            );
            toast(`${view.name} becomes ${SIZE_LABELS[chosen.size]}`, {
                description: chosen.move
                    ? 'It moves to a fresh machine with everything copied over.'
                    : 'Once the turns on it now end.',
            });
            onClose();
        } catch (error) {
            toast('Couldn’t change its size', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            setBusy(false);
            rereadMachine(view.id);
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            dismissible={!busy}
            title={`Change ${view.name}’s size`}
            description={`It stays on ${view.host ? HOST_NAMES[view.host] : 'its host'} in ${placeName(view.region) ?? 'its region'}. These are the sizes it can be right now.`}
            mark={<Server className="h-5 w-5" strokeWidth={1.75} />}
            testId="resize-machine"
            footer={
                <>
                    <button
                        type="button"
                        onClick={onClose}
                        className={BUTTON_GHOST}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        disabled={!chosen || chosen.now || busy}
                        onClick={() => void go()}
                        className={BUTTON_PRIMARY}
                    >
                        {!chosen || chosen.now
                            ? 'Pick a size'
                            : `Change to ${SIZE_LABELS[chosen.size]} · ${perMonth(chosen.usd)}`}
                    </button>
                </>
            }
        >
            <div
                role="radiogroup"
                aria-label="Size"
                className="grid gap-1.5 pb-2"
            >
                {!sizes.data && (
                    <p className="text-[13.5px] text-muted-foreground">
                        Reading the sizes…
                    </p>
                )}
                {options.map((o) => {
                    const diff = current
                        ? dayPrice(o.usd) - dayPrice(current.usd)
                        : 0;
                    const checked = chosen?.size === o.size;
                    return (
                        <button
                            key={o.size}
                            type="button"
                            role="radio"
                            aria-checked={checked}
                            onClick={() => setPick(o.size)}
                            className={cn(
                                'flex w-full items-start gap-3 rounded-[20px] px-3.5 py-3 text-left ring-1 ring-inset transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                                checked
                                    ? 'bg-foreground/[0.05] ring-[1.5px] ring-foreground/60'
                                    : 'ring-border hover:bg-foreground/[0.03] dark:ring-foreground/[0.1]'
                            )}
                        >
                            <span
                                className={cn(
                                    'mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full ring-[1.5px] ring-inset',
                                    checked
                                        ? 'ring-foreground'
                                        : 'ring-foreground/30'
                                )}
                            >
                                {checked && (
                                    <span className="h-2 w-2 rounded-full bg-foreground" />
                                )}
                            </span>
                            <span className="grid min-w-0 flex-1 gap-px">
                                <span className="flex items-center gap-2 text-[14px] font-medium">
                                    {SIZE_LABELS[o.size]}
                                    {o.now && (
                                        <span className="rounded-full px-1.5 py-px text-[11px] font-normal text-muted-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.12]">
                                            Now
                                        </span>
                                    )}
                                </span>
                                <span className="text-[12.5px] text-muted-foreground">
                                    Up to {o.atOnce} agents working at once
                                </span>
                                <span className="text-[12.5px] text-muted-foreground">
                                    {o.cpu} vCPU · {o.memoryGb} GB memory ·{' '}
                                    {o.diskGb} GB disk
                                </span>
                                {o.move && (
                                    <span className="mt-0.5 text-[12.5px] text-muted-foreground">
                                        Moves to a fresh machine and copies
                                        everything over: it uses{' '}
                                        {Math.round(
                                            view.health?.diskUsedGb ?? 0
                                        )}{' '}
                                        GB, this holds {o.diskGb}.
                                    </span>
                                )}
                            </span>
                            <span className="shrink-0 text-right text-[14px] font-medium tabular-nums">
                                {usd(o.usd)}
                                <span className="text-[12.5px] font-normal text-muted-foreground">
                                    {' '}
                                    a month
                                </span>
                                {!o.now && (
                                    <span className="block text-[11.5px] font-normal text-muted-foreground">{`${diff > 0 ? '+' : '−'}${usd(Math.abs(diff))} a day`}</span>
                                )}
                            </span>
                        </button>
                    );
                })}
                <p className="mt-1 text-[12.5px] text-muted-foreground">
                    Applies once the turns on it now end. Agents carry on until
                    then; nothing on it is lost.
                </p>
            </div>
        </ShellDialog>
    );
}

/** What goes and what happens, then the delete: its agents move back to their own sandboxes first, server-side. */
function DeleteDialog({
    view,
    onIt,
    onClose,
    onDeleted,
}: {
    view: MachineView;
    onIt: string[];
    onClose: () => void;
    onDeleted: () => void;
}) {
    const client = useWorkClient();
    const [busy, setBusy] = useState(false);
    const own = view.kind === 'own';
    const verb = own ? 'Remove' : 'Delete';
    const goes = own
        ? [
              `NoClick’s part of it: ${ownDevice(view.os).what === 'Mac' ? 'its VM and ' : ''}the agents’ sealed containers.`,
          ]
        : [
              `Its disk and everything on it${view.health ? `: ${Math.round(view.health.diskUsedGb)} GB of files` : ''}.`,
              ...view.ports.map(
                  (p) =>
                      `Its public address ${p.url.replace(/^https:\/\//, '')}.`
              ),
          ];
    const happens = [
        ...(onIt.length
            ? [
                  `${andList(onIt)} ${onIt.length === 1 ? 'moves back to its own cloud sandbox, with its files' : 'move back to their own cloud sandboxes, with their files'}.`,
              ]
            : []),
        own
            ? 'NoClick uninstalls itself the next time it’s on. Your own files on it stay.'
            : `The charge stops today. This month comes to ${usd(view.spentUsdThisMonth)}.`,
    ];
    const run = async () => {
        setBusy(true);
        try {
            await Machine.fromId(view.id, {
                client,
                user: view.userId,
            }).delete();
            toast(`${view.name} was ${own ? 'removed' : 'deleted'}`, {
                description: onIt.length
                    ? `${andList(onIt)} now ${onIt.length === 1 ? 'works in its' : 'work in their'} own cloud sandbox${onIt.length === 1 ? '' : 'es'}.`
                    : own
                      ? 'NoClick uninstalls itself from it next time it’s on.'
                      : 'The charge stops today.',
            });
            rereadMachine(view.id);
            onDeleted();
        } catch (error) {
            toast(`Couldn’t ${verb.toLowerCase()} ${view.name}`, {
                description:
                    error instanceof Error ? error.message : String(error),
            });
            setBusy(false);
        }
    };
    const list = (xs: string[]) => (
        <ul className="mt-1.5 grid gap-1.5">
            {xs.map((x) => (
                <li key={x} className="flex gap-2 text-[13.5px] leading-snug">
                    <span
                        aria-hidden
                        className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-foreground/50"
                    />
                    {x}
                </li>
            ))}
        </ul>
    );
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            dismissible={!busy}
            tone="danger"
            title={`${verb} ${view.name}?`}
            description={
                own
                    ? 'NoClick stops using this computer.'
                    : 'This can’t be undone.'
            }
            mark={<Trash2 className="h-5 w-5" strokeWidth={1.75} />}
            testId="delete-machine"
            footer={
                <>
                    <button
                        type="button"
                        disabled={busy}
                        onClick={onClose}
                        className={BUTTON_GHOST}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() => void run()}
                        className={BUTTON_DANGER}
                    >
                        {busy
                            ? `${own ? 'Removing' : 'Deleting'}…`
                            : `${verb} ${view.name}`}
                    </button>
                </>
            }
        >
            <div className="grid gap-4 pb-2">
                <div>
                    <p className="text-[12.5px] font-medium text-muted-foreground">
                        What goes
                    </p>
                    {list(goes)}
                </div>
                <div>
                    <p className="text-[12.5px] font-medium text-muted-foreground">
                        What happens
                    </p>
                    {list(happens)}
                </div>
            </div>
        </ShellDialog>
    );
}
