// A machine's own page, a NoClick machine or a computer of yours: the agent page's sibling header (its lead, name, kind
// and three figures: this month's cost, who's working, how long it's been up), a state that isn't plain running saying
// what it means with its one action, then what's on it, its health as a verdict with the fix, a shell in the page (and
// SSH from a terminal), its user's home folder's files, and its settings, for your own computer as for a NoClick
// machine. Read from `GET /v1/machines/{id}`.
import { useState, type ReactNode } from 'react';
import { ChevronDown, Laptop, Server, SquareTerminal } from 'lucide-react';
import { getMachineAccess } from '@/sdk/owner';
import type { OwnComputer } from '@/screens/resources/knowledge';
import { relTime } from '@/ui/primitives';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { Section, Surface } from '@/screens/resources/ui';
import { PAGE_TITLE } from '@/ui/titles';
import { CopyButton } from '@/ui/CopyButton';
import { formatDollars } from '@/lib/formatters';
import { cn } from '@/ui/utils';
import { useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import { useMachine } from '../profile/reads';
import { useMachineFrames } from './frames';
import { openMachineShell, powerAction } from './machineApi';
import { MachineAgents } from './MachineAgents';
import { MachineDisk } from './MachineDisk';
import { MachineSettings, ResizeDialog } from './MachineSettings';
import {
    barsOf,
    canWork,
    isUp,
    kindLine,
    ownDevice,
    perMonth,
    SIZE_LABELS,
    slotsOf,
    stateInfo,
    toMachineView,
    upLine,
    verdictOf,
    type MachineView,
    type Tone,
} from './machineView';
import { machineKey, VETTING_KEY } from './reads';
import { ShellDrawer } from './ShellDrawer';

const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);
const STAT =
    'min-w-0 rounded-2xl border border-border bg-card px-4 py-3 dark:border-foreground/[0.08] dark:bg-foreground/[0.02]';
const DOT: Record<Tone, string> = {
    ok: 'bg-emerald-500',
    busy: 'bg-foreground/50 animate-pulse motion-reduce:animate-none',
    off: 'ring-[1.5px] ring-inset ring-foreground/40',
    bad: 'bg-red-500',
};
/** An inline action inside a sentence, as the page's other links are. */
export const INLINE_ACT =
    'font-medium text-foreground underline decoration-foreground/30 underline-offset-[3px] transition-colors hover:decoration-foreground';
/** The disclosure under a section that opens what most people don't need. */
const DISCLOSE =
    'mt-4 inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground';

/** One machine as its page reads it, read again on each of its frames. */
export function useMachineView(id: string) {
    const read = useMachine(id);
    useMachineFrames(id, machineKey(id));
    return { view: read.data ? toMachineView(read.data.raw) : null, read };
}

export function StateDot({
    tone,
    className,
}: {
    tone: Tone;
    className?: string;
}) {
    return (
        <span
            aria-hidden
            className={cn(
                'h-2 w-2 shrink-0 rounded-full',
                DOT[tone],
                className
            )}
        />
    );
}

/** The lead, name and kind; then the state when it isn't plain running, and the three figures. */
export function MachineHeader({
    view,
    now,
    company,
    onAction,
    lead = true,
}: {
    view: MachineView;
    now: number;
    company?: string | null;
    onAction: (action: 'start' | 'restart') => void;
    /** False where the page around it already names the machine (a space's Resources tab). */
    lead?: boolean;
}) {
    const s = stateInfo(view, company);
    const Icon =
        view.kind === 'own' && ownDevice(view.os).what === 'Mac'
            ? Laptop
            : Server;
    const slots = slotsOf(view);
    const working = canWork(view) ? view.workingCount : 0;
    const seen = view.lastSeenAt
        ? `checked in ${relTime(view.lastSeenAt, new Date(now).toISOString())}`
        : 'never checked in';
    const third: [string, string] = (() => {
        switch (view.status) {
            case 'running':
                return [
                    view.kind === 'own' ? 'Online' : upLine(view, now),
                    seen,
                ];
            case 'offline':
                return [
                    'Offline',
                    view.lastSeenAt ? `last ${seen}` : 'never checked in',
                ];
            case 'provisioning':
                return view.kind === 'own'
                    ? ['Not yet', 'never checked in']
                    : ['Starting', 'ready in about 3 minutes'];
            case 'updating':
                return [
                    upLine(view, now),
                    view.pending
                        ? `becomes ${SIZE_LABELS[view.pending.size]} next`
                        : 'changing size',
                ];
            case 'stopped':
                return ['Stopped', 'start it to work again'];
            case 'awaiting_approval':
                return ['Not yet', 'starts once approved'];
            case 'restarting':
                return ['Restarting', 'back in about a minute'];
            default:
                return [s.label, seen];
        }
    })();
    const first: [string, string] =
        view.kind === 'own'
            ? ['Free', 'your own machine']
            : view.status === 'awaiting_approval'
              ? [formatDollars(0), 'nothing until it starts']
              : [
                    formatDollars(view.spentUsdThisMonth),
                    `this month · ${view.monthlyUsd !== null ? perMonth(view.monthlyUsd) : ''}`,
                ];
    return (
        <>
            {lead && (
                <header
                    className="flex flex-wrap items-center gap-4"
                    data-testid="machine-head"
                >
                    <span className="relative grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-foreground/[0.06]">
                        <Icon
                            className="h-5 w-5 text-foreground/75"
                            strokeWidth={1.75}
                        />
                        <StateDot
                            tone={s.tone}
                            className="absolute bottom-1 right-1 ring-2 ring-background"
                        />
                    </span>
                    <div className="min-w-0 flex-1">
                        <h1
                            className={cn(
                                'min-w-0 break-words sm:truncate',
                                PAGE_TITLE
                            )}
                        >
                            {view.name}
                        </h1>
                        <p className="mt-1 text-[14px] leading-snug text-muted-foreground sm:truncate">
                            {kindLine(view)}
                        </p>
                    </div>
                </header>
            )}
            {view.status !== 'running' && (
                <div
                    className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-foreground/[0.04] px-4 py-3 text-[13.5px]"
                    data-testid="machine-state"
                >
                    <span className="inline-flex shrink-0 items-center gap-2 rounded-full bg-background px-2.5 py-1 text-[12.5px] font-medium ring-1 ring-inset ring-border dark:bg-foreground/[0.06] dark:ring-foreground/[0.1]">
                        <StateDot tone={s.tone} />
                        {s.label}
                    </span>
                    <span className="min-w-0 flex-1 text-muted-foreground">
                        {s.meaning}
                    </span>
                    {s.action && (
                        <button
                            type="button"
                            onClick={() => onAction(s.action!)}
                            className={SMALL_SECONDARY}
                        >
                            {s.action === 'start' ? 'Start it' : 'Restart it'}
                        </button>
                    )}
                </div>
            )}
            <div className="mt-5 grid gap-2.5 sm:grid-cols-3">
                <Stat
                    testId="machine-spend"
                    figure={first[0]}
                    line={first[1]}
                />
                <Stat
                    testId="machine-working"
                    figure={slots ? `${working} of ${slots}` : String(working)}
                    line={
                        canWork(view)
                            ? 'agents working now'
                            : 'no agent can work now'
                    }
                />
                <Stat testId="machine-up" figure={third[0]} line={third[1]} />
            </div>
        </>
    );
}

function Stat({
    figure,
    line,
    testId,
}: {
    figure: ReactNode;
    line: ReactNode;
    testId: string;
}) {
    return (
        <div className={STAT} data-testid={testId}>
            <p className="truncate text-[17px] font-semibold tabular-nums text-foreground">
                {figure}
            </p>
            <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">
                {line}
            </p>
        </div>
    );
}

/** Its health: NoClick's verdict and the fix, with the three bars a tap away. */
function Health({
    view,
    now,
    onFix,
}: {
    view: MachineView;
    now: number;
    onFix: (action: 'resize' | 'files') => void;
}) {
    const [more, setMore] = useState(false);
    const verdict = verdictOf(view, now);
    const seen =
        view.lastSeenAt && (isUp(view) || view.status === 'offline')
            ? `Checked in ${relTime(view.lastSeenAt, new Date(now).toISOString())}`
            : undefined;
    const bars =
        view.health && canWork(view) ? barsOf(view, view.health) : null;
    return (
        <Section title="Health" meta={seen}>
            <Surface>
                <div
                    className="flex items-start gap-3 px-4 py-3.5 sm:px-5"
                    data-testid="machine-verdict"
                >
                    <StateDot tone={verdict.tone} className="mt-[7px]" />
                    <p className="min-w-0 flex-1 text-[14px] leading-relaxed">
                        {verdict.text}
                        {verdict.fix &&
                            (verdict.fix.action === 'settings' ? (
                                ` ${verdict.fix.label}.`
                            ) : (
                                <>
                                    {' '}
                                    <button
                                        type="button"
                                        onClick={() =>
                                            onFix(
                                                verdict.fix!.action as
                                                    | 'resize'
                                                    | 'files'
                                            )
                                        }
                                        className={INLINE_ACT}
                                    >
                                        {verdict.fix.label}
                                    </button>
                                </>
                            ))}
                    </p>
                    {bars && (
                        <button
                            type="button"
                            aria-expanded={more}
                            onClick={() => setMore(!more)}
                            className="h-7 shrink-0 rounded-full px-2.5 text-[12.5px] font-medium text-muted-foreground ring-1 ring-inset ring-border transition-colors hover:text-foreground dark:ring-foreground/[0.12]"
                        >
                            {more ? 'Hide details' : 'Details'}
                        </button>
                    )}
                </div>
                {more && bars && (
                    <div
                        className="grid gap-3.5 border-t border-border px-4 py-4 sm:px-5 dark:border-foreground/[0.06]"
                        data-testid="machine-bars"
                    >
                        {bars.map((b) => (
                            <div key={b.label} className="grid gap-1.5">
                                <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
                                    <span>
                                        {b.label}{' '}
                                        <span className="text-muted-foreground">
                                            · {b.word}
                                        </span>
                                    </span>
                                    <span className="tabular-nums text-muted-foreground">
                                        {b.numbers}
                                    </span>
                                </div>
                                <span className="h-1.5 overflow-hidden rounded-full bg-foreground/[0.08]">
                                    <span
                                        className={cn(
                                            'block h-full rounded-full',
                                            b.ratio > 0.85
                                                ? 'bg-red-500'
                                                : 'bg-foreground/60'
                                        )}
                                        style={{
                                            width: `${Math.round(b.ratio * 100)}%`,
                                        }}
                                    />
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </Surface>
        </Section>
    );
}

/** A shell in the page, on any machine (on your own computer as NoClick's `noclick` user, in NoClick's VM on a Mac),
 *  and its command line for a terminal. */
function Shell({ view }: { view: MachineView }) {
    const client = useWorkClient();
    const [open, setOpen] = useState(false);
    const [closed, setClosed] = useState(false);
    const [ssh, setSsh] = useState(false);
    const own = view.kind === 'own';
    const device = ownDevice(view.os).what;
    const running = isUp(view);
    const command = `noclick machines ssh ${view.name}`;
    return (
        <Section title="Shell">
            <p className="-mt-1 mb-3 text-[13.5px] text-muted-foreground">
                {own
                    ? `Type commands ${device === 'Mac' ? 'in NoClick’s VM on your Mac' : `on your ${device}`} as the noclick user, without sudo.`
                    : 'Type commands on this machine, as if you were sitting at it.'}
            </p>
            {open ? (
                <>
                    <Surface>
                        <ShellDrawer
                            label={`Your shell on ${view.name}`}
                            running={running}
                            open={() =>
                                openMachineShell(client, view.id, view.userId)
                            }
                            asleep={`${view.name} isn’t running, so the shell ended.`}
                            onClose={() => {
                                setOpen(false);
                                setClosed(true);
                            }}
                            className="border-t-0"
                        />
                    </Surface>
                    <p className="mt-2 text-[12.5px] text-muted-foreground">
                        It closes after 15 minutes with nothing typed. Closing
                        it stops anything still running in it.
                    </p>
                </>
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-3">
                        <button
                            type="button"
                            disabled={!running}
                            onClick={() => {
                                setOpen(true);
                                setClosed(false);
                            }}
                            className={BUTTON_PRIMARY}
                        >
                            <SquareTerminal
                                className="h-4 w-4"
                                strokeWidth={1.75}
                            />
                            Open a shell
                        </button>
                        <span className="text-[13px] text-muted-foreground">
                            {running
                                ? 'Signed in already. No keys, no setup.'
                                : `${view.name} is ${stateInfo(view).label.toLowerCase()}. ${own ? 'A shell opens once it’s online.' : 'Start it to open a shell.'}`}
                        </span>
                    </div>
                    {closed && (
                        <p className="mt-2 text-[12.5px] text-muted-foreground">
                            Shell closed. Anything still running in it stopped.
                        </p>
                    )}
                </>
            )}
            <button
                type="button"
                aria-expanded={ssh}
                onClick={() => setSsh(!ssh)}
                className={cn(DISCLOSE, '-ml-3')}
            >
                {own ? 'From any terminal' : 'From your own computer'}
                <ChevronDown
                    className={cn(
                        'h-4 w-4 transition-transform',
                        ssh && 'rotate-180'
                    )}
                />
            </button>
            {ssh && (
                <div className="mt-2" data-testid="machine-ssh">
                    <p className="text-[13.5px] text-muted-foreground">
                        Type commands on {view.name} from the terminal app on{' '}
                        {own ? 'any computer' : 'your own computer'}. No keys to
                        add, and nothing to set up on the machine.
                    </p>
                    <div className="mt-2.5 flex items-center gap-2 rounded-full bg-foreground/[0.05] py-1 pl-4 pr-1">
                        <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">
                            <span className="select-none text-muted-foreground">
                                ${' '}
                            </span>
                            {command}
                        </code>
                        <CopyButton value={command} />
                    </div>
                    <p className="mt-2 text-[12.5px] leading-snug text-muted-foreground">
                        Needs the NoClick command line, once:{' '}
                        <code className="font-mono">
                            {"pip install 'noclick[cli]'"}
                        </code>
                        , then <code className="font-mono">noclick login</code>.
                    </p>
                </div>
            )}
        </Section>
    );
}

export interface MachineDetailProps {
    view: MachineView;
    now: number;
    /** Your own computer as Resources lists it, for what NoClick uses of it. */
    own?: OwnComputer | null;
    /** Gone: where the page goes next. */
    onDeleted: () => void;
}

/** Everything under the header: what's on it, its health, getting in, its files, its settings. */
export function MachineSections({
    view,
    now,
    own,
    onDeleted,
}: MachineDetailProps) {
    const [resizing, setResizing] = useState(false);
    const [filesAsked, setFilesAsked] = useState(0);
    return (
        <div data-testid="machine-sections">
            <MachineAgents view={view} />
            <Health
                view={view}
                now={now}
                onFix={(action) => {
                    if (action === 'resize') setResizing(true);
                    else {
                        setFilesAsked((n) => n + 1);
                        document
                            .querySelector('[data-testid="machine-files"]')
                            ?.scrollIntoView({
                                behavior: 'smooth',
                                block: 'start',
                            });
                    }
                }}
            />
            <Shell view={view} />
            <MachineDisk view={view} key={filesAsked} />
            <MachineSettings
                view={view}
                own={own ?? null}
                onDeleted={onDeleted}
                onResize={() => setResizing(true)}
            />
            {resizing && (
                <ResizeDialog view={view} onClose={() => setResizing(false)} />
            )}
        </div>
    );
}

/** Whose approval a held machine waits for: the company the account sent. */
export function useVettingCompany(): string | null {
    const vetting = useWorkV1(VETTING_KEY, (c) => getMachineAccess(c));
    return vetting.data?.company_name ?? null;
}

/** A machine read by its id: its header (or only its state and figures, `lead` false) and every section. */
export function MachineDetail({
    id,
    now,
    own,
    onDeleted,
    lead = true,
    between,
}: {
    id: string;
    now: number;
    own?: OwnComputer | null;
    onDeleted: () => void;
    lead?: boolean;
    /** What goes under the header, before the sections (a computer of yours still pairing: its command). */
    between?: ReactNode;
}) {
    const client = useWorkClient();
    const { view, read } = useMachineView(id);
    const company = useVettingCompany();
    if (!view)
        return read.error !== undefined ? (
            <p role="alert" className="mt-6 text-[14px] text-muted-foreground">
                Couldn’t read it:{' '}
                {read.error instanceof Error
                    ? read.error.message
                    : String(read.error)}{' '}
                <button
                    type="button"
                    className={INLINE_ACT}
                    onClick={() => void read.refresh()}
                >
                    Try again
                </button>
            </p>
        ) : (
            <div
                aria-busy
                className="mt-6 h-40 animate-pulse rounded-2xl bg-foreground/[0.03]"
            />
        );
    return (
        <div data-testid="machine-detail">
            <MachineHeader
                view={view}
                now={now}
                company={company}
                lead={lead}
                onAction={(action) => void powerAction(client, view, action)}
            />
            {between}
            <MachineSections
                view={view}
                now={now}
                own={own}
                onDeleted={onDeleted}
            />
        </div>
    );
}
