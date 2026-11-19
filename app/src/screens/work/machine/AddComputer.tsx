// Adding a computer of yours, the one dialog both Resources' "Add your computer" and New agent's Runs in open. A code
// is made as it opens, with no name asked (the computer takes its own, renamed later if you like). What agents may do
// there reads as one sentence above the steps (three quarters of it, asking before running apps or test databases,
// unless you say); Change slides to the share slider and the apps choice, saved on the computer as they're picked, and
// Done slides back. Then three steps tick as the computer's frames say it moved: copy the command (whole, to read
// before it's run; Unattended gives it --yes, for SSH, cloud-init or a script), run it on the computer (installing there, or why that computer can't), and it's online, with what
// it is and Use it.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Check, CircleDollarSign, Copy, Laptop, Moon, RefreshCw, Trash2 } from 'lucide-react';
import { useNow } from '@/lib/clock';
import { invalidateV1 } from '@/sdk/useV1';
import { NoClickError, NotAvailable, type AppTesting } from 'noclick';
import { addOwnComputer, getOwnComputer, newPairing, setComputerAppTesting, type OwnComputer, type PairingCommands } from '@/screens/resources/knowledge';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import { AGENTS_ENABLED_KEY, AGENTS_NOT_ENABLED, OWN_KEY, useAgentsOnMachines } from '../resources/machines';
import { BackLink, slideIn } from './BackLink';
import { useMachineFrames } from './frames';
import { DEFAULT_SHARE, shareLabel } from './share';
import { ShareChoice } from './ShareChoice';
import { Steps, type Step } from './Steps';

const UNINSTALL = 'sudo noclick-machine uninstall';
// On a Mac, NoClick's own folder holds it, and removing it takes all of it (the guide's words).
const UNINSTALL_MAC = '~/Library/Application Support/NoClick/bin/noclick-machine uninstall';
const RUNS_ON = 'Linux (Ubuntu or Debian, x86-64 or ARM64), a Mac with Apple silicon, or Windows through WSL 2';
const RUNS_ON_MAC = 'In Terminal on your Mac (Apple silicon, macOS 13 or later), as you: it never needs sudo.';

type System = 'linux' | 'mac';
const SYSTEMS: { id: System; label: string }[] = [
    { id: 'linux', label: 'Linux or Windows' },
    { id: 'mac', label: 'Mac' },
];
/** Run where someone answers its "Go ahead?", or unattended (`--yes`), where nobody can. */
type Runs = 'asks' | 'unattended';
const RUNS: { id: Runs; label: string }[] = [
    { id: 'asks', label: 'Asks first' },
    { id: 'unattended', label: 'Unattended' },
];
const UNATTENDED = 'Over SSH, from cloud-init or a script: with --yes it goes ahead without asking.';

/** Whether agents may run apps and test databases on it (the API's `app_testing`), as it's picked and as it's said. */
const APP_MODES: { id: AppTesting; label: string }[] = [
    { id: 'ask_first', label: 'Ask first' },
    { id: 'by_itself', label: 'Yes' },
    { id: 'never', label: 'No' },
];
const APPS_SAID: Record<AppTesting, string> = {
    ask_first: 'ask before running apps or test databases',
    by_itself: 'can run apps and test databases',
    never: 'won’t run apps or test databases',
};
/** A computer of yours asks first unless you say (the API's default for one). */
const NEW_APP_TESTING: AppTesting = 'ask_first';
const APPS_QUESTION = 'Let agents run apps and test databases on this computer';

/** What agents may do on a computer of yours, as one sentence: the part they use (and, once it's online, how many
 *  work at once there) and whether they run apps and test databases. */
export function choicesSentence(share: number, appTesting: AppTesting, atOnce: number | null): string {
    const part = share === 1 ? 'all of it' : `${shareLabel(share).toLowerCase()} of it`;
    return `Agents may use ${part}${atOnce ? `, up to ${atOnce} at once,` : ','} and ${APPS_SAID[appTesting]}.`;
}

export interface AddComputerProps {
    /** What Use it does with the computer once it's online, and what its button says. */
    use: { label: string; onUse: (computer: OwnComputer) => void };
    /** Closed: the computer being added, where one was made. */
    onClose: (computer: OwnComputer | null) => void;
}

export function AddComputer({ use, onClose }: AddComputerProps) {
    const client = useWorkClient();
    const enabled = useAgentsOnMachines();
    // The command comes only with a code as it's made: a read later carries neither. Its forms (a Mac's has no sudo)
    // where the API gives them, else Linux's alone.
    const [made, setMade] = useState<{ computer: OwnComputer; command: string; commands: PairingCommands | null } | null>(null);
    const [system, setSystem] = useState<System>('linux');
    const [runs, setRuns] = useState<Runs>('asks');
    const [refused, setRefused] = useState<string | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [copied, setCopied] = useState(false);
    const [renewing, setRenewing] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const [page, setPage] = useState<'main' | 'settings'>('main');
    const [returned, setReturned] = useState(false);
    // The apps choice sent, shown until the computer as saved says it; a refusal puts it back, saying why.
    const [apps, setApps] = useState<AppTesting | null>(null);
    const [appsRefused, setAppsRefused] = useState<{ message: string; nextStep: string | null } | null>(null);
    const minted = useRef(-1);
    useEffect(() => {
        if (enabled !== true || minted.current === attempt) return;
        minted.current = attempt;
        void (async () => {
            try {
                const computer = await addOwnComputer(client, { appTesting: NEW_APP_TESTING });
                setMade({ computer, command: computer.pairing?.command ?? '', commands: computer.pairing?.commands ?? null });
                invalidateV1(OWN_KEY);
            } catch (error) {
                if (error instanceof NotAvailable) {
                    setRefused(error.message || AGENTS_NOT_ENABLED);
                    invalidateV1(AGENTS_ENABLED_KEY);
                } else setFailed(error instanceof Error ? error.message : String(error));
            }
        })();
    }, [enabled, client, attempt]);

    const id = made?.computer.id ?? null;
    const key = id ? `machines/${id}` : null;
    const read = useWorkV1(key, (c) => getOwnComputer(c, id!));
    useMachineFrames(id, key);
    const computer = read.data ?? made?.computer ?? null;

    const pairing = computer?.pairing ?? null;
    const online = computer?.status === 'running';
    const offline = computer?.status === 'offline';
    const installing = !online && !offline && !!pairing?.installingOn;
    const ran = installing || online || offline;
    const expiresAt = pairing?.expiresAt ? Date.parse(pairing.expiresAt) : null;
    // A second at a time while the code counts down, so it reads as expired the moment it is.
    useNow(!!made && !ran);
    const now = Date.now();
    const expired = !ran && expiresAt !== null && expiresAt <= now;
    const refusal = !ran && !expired ? (pairing?.refused ?? null) : null;

    const renew = async () => {
        if (!id) return;
        setRenewing(true);
        try {
            const computer = await newPairing(client, id);
            setMade({ computer, command: computer.pairing?.command ?? '', commands: computer.pairing?.commands ?? null });
            setCopied(false);
            invalidateV1(key!);
        } catch (error) {
            setFailed(error instanceof Error ? error.message : String(error));
        } finally {
            setRenewing(false);
        }
    };
    const close = () => onClose(computer);
    const name = computer?.hostname ?? computer?.name ?? 'It';
    const minutes = expiresAt !== null ? Math.ceil((expiresAt - now) / 60_000) : null;
    const mac = system === 'mac' && !!made?.commands;
    const unattended = runs === 'unattended' ? (made?.commands?.unattended ?? null) : null;
    const command = made ? (made.commands ? (unattended ?? made.commands)[system] : made.command) : '';

    const steps: Step[] = [
        {
            id: 'copy',
            title: expired ? 'The code expired' : copied || ran ? 'Copied the command' : 'Copy this command',
            status: expired ? 'error' : copied || ran ? 'done' : 'now',
            body: ran ? null : made ? (
                <>
                    {made.commands && !expired && (
                        <div className="mt-2 flex flex-wrap gap-2">
                            <Segmented label="Its system" options={SYSTEMS} value={system} onChange={setSystem} />
                            {made.commands.unattended && <Segmented label="How it runs" options={RUNS} value={runs} onChange={setRuns} />}
                        </div>
                    )}
                    <Command command={command} expired={expired} onCopied={() => setCopied(true)} />
                    {expired ? (
                        <div className="mt-2 flex flex-wrap items-center gap-2 px-1">
                            <span className="text-[12.5px] text-foreground">A code works once, for 30 minutes.</span>
                            <button type="button" disabled={renewing} onClick={() => void renew()} className={cn(BUTTON_SECONDARY, 'h-7 px-3 text-[12.5px]')}>
                                <RefreshCw className="h-3 w-3" strokeWidth={2} />
                                Get a new code
                            </button>
                        </div>
                    ) : (
                        minutes !== null && <p className="mt-1.5 px-1 text-[12px] tabular-nums text-muted-foreground">Works once, for {minutes} more {minutes === 1 ? 'minute' : 'minutes'}.</p>
                    )}
                </>
            ) : (
                <p className="mt-1 text-[12.5px] text-muted-foreground">Making a code…</p>
            ),
        },
        {
            id: 'run',
            title: refusal ? `${refusal.hostname ?? 'That computer'} can’t run it` : installing ? `Installing on ${pairing!.installingOn}` : online || offline ? `Installed on ${name}` : 'Run it on your computer',
            status: refusal ? 'error' : installing ? 'busy' : online || offline ? 'done' : copied && !expired ? 'now' : 'wait',
            body: refusal ? (
                <>
                    <p className="mt-1 text-[12.5px] leading-snug text-red-600 dark:text-red-400">{refusal.message}</p>
                    {refusal.nextStep && <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">{refusal.nextStep}</p>}
                </>
            ) : installing ? (
                <p className="mt-1 text-[12.5px] text-muted-foreground">Docker and gVisor go on first if it hasn’t got them.</p>
            ) : online || offline ? null : (
                <>
                    <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">{mac ? RUNS_ON_MAC : `In a terminal on it, with sudo: ${RUNS_ON}.`}</p>
                    {unattended && <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">{UNATTENDED}</p>}
                </>
            ),
        },
        {
            id: 'online',
            title: online ? `${name} is online` : offline ? `${name} went offline` : 'It comes online here',
            status: online ? 'done' : offline ? 'error' : 'wait',
            body: online ? (
                <>
                    <p className="mt-1 text-[12.5px] text-muted-foreground">{[computer!.os, computer!.cpu && `${computer!.cpu} CPUs`, computer!.memoryGb && `${computer!.memoryGb} GB`].filter(Boolean).join(' · ')}</p>
                    <button type="button" onClick={() => use.onUse(computer!)} className={cn(BUTTON_PRIMARY, 'mt-4')}>
                        {use.label}
                    </button>
                </>
            ) : (
                <p className="mt-1 text-[12.5px] text-muted-foreground">{offline ? 'It comes back once it’s on and online.' : installing ? 'Once it’s installed.' : 'You can close this: it comes online all the same.'}</p>
            ),
        },
    ];

    const appTesting = apps ?? computer?.appTesting ?? NEW_APP_TESTING;
    const sentence = choicesSentence(computer?.agentShare ?? DEFAULT_SHARE, appTesting, online ? computer!.conversationsAtOnce : null);
    const saved = (next: OwnComputer) => {
        read.mutate(next);
        invalidateV1(OWN_KEY);
    };
    const pickApps = async (next: AppTesting) => {
        if (!computer || next === appTesting) return;
        setApps(next);
        setAppsRefused(null);
        try {
            saved(await setComputerAppTesting(client, computer.id, next));
        } catch (error) {
            setAppsRefused({ message: error instanceof Error ? error.message : String(error), nextStep: error instanceof NoClickError ? error.nextStep : null });
        } finally {
            setApps(null);
        }
    };
    const settings = page === 'settings' && !!computer;
    const go = (to: 'main' | 'settings') => {
        setReturned(to === 'main');
        setPage(to);
    };

    const stopped = refused ?? (enabled === false ? AGENTS_NOT_ENABLED : null);
    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && close()}
            title={settings ? 'What agents may do here' : 'Add your computer'}
            description={
                settings
                    ? `On ${computer!.hostname ?? 'this computer'}${online ? '' : ' once it’s added'}.`
                    : online
                      ? 'Agents run on it, in sandboxed containers, while it’s awake.'
                      : 'Agents run on it, in sandboxed containers that can’t touch the rest of it.'
            }
            mark={
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-foreground/[0.06] ring-1 ring-inset ring-foreground/[0.05]">
                    <Laptop className="h-5 w-5" strokeWidth={1.75} />
                </span>
            }
            markTile={false}
            testId="add-computer"
            footer={
                settings ? (
                    <button type="button" onClick={() => go('main')} className={BUTTON_PRIMARY}>
                        Done
                    </button>
                ) : online ? undefined : (
                    <button type="button" onClick={close} className={BUTTON_GHOST}>
                        {installing ? 'Close; it carries on' : 'Close'}
                    </button>
                )
            }
        >
            {stopped ? (
                <p role="status" className="pb-2 text-[13.5px] text-foreground" data-testid="agents-not-enabled">
                    {stopped}
                </p>
            ) : failed && !made ? (
                <div role="status" className="flex flex-wrap items-center gap-2 pb-2">
                    <span className="text-[13.5px] text-foreground">Couldn’t make a code: {failed}</span>
                    <button
                        type="button"
                        onClick={() => {
                            setFailed(null);
                            setAttempt((n) => n + 1);
                        }}
                        className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}
                    >
                        Try again
                    </button>
                </div>
            ) : settings ? (
                <div key="settings" className={cn('pb-2', slideIn(false))} data-testid="computer-choices">
                    <BackLink label="Add your computer" onClick={() => go('main')} />
                    <ShareChoice computer={computer!} mac={mac} onSaved={saved} />
                    <div className="mt-6">
                        <p className="text-[14px] font-medium leading-snug text-foreground">{APPS_QUESTION}</p>
                        <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">So an agent can start your app and run its tests against a real database, the way a developer would. It all happens inside the agent’s own sandbox.</p>
                        <Segmented label={APPS_QUESTION} options={APP_MODES} value={appTesting} onChange={(next) => void pickApps(next)} className="mt-3" />
                        {appsRefused && (
                            <p role="alert" className="mt-2 text-[12.5px] leading-snug text-red-600 dark:text-red-400">
                                {appsRefused.message}
                                {appsRefused.nextStep ? ` ${appsRefused.nextStep}` : ''}
                            </p>
                        )}
                    </div>
                </div>
            ) : (
                <div key="main" className={cn('pb-2', returned && slideIn(true))}>
                    <div className="mb-5 flex items-center gap-3 rounded-[20px] py-3 pl-4 pr-3 ring-1 ring-inset ring-border dark:ring-foreground/[0.1]">
                        <p data-testid="choices-sentence" className="min-w-0 flex-1 text-[13.5px] leading-snug text-foreground">
                            {sentence}
                        </p>
                        <button type="button" disabled={!computer} onClick={() => go('settings')} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                            Change
                        </button>
                    </div>
                    <Steps steps={steps} />
                    {failed && <p className="pb-2 text-[12.5px] text-red-600 dark:text-red-400">{failed}</p>}
                    <Facts mac={mac} />
                </div>
            )}
        </ShellDialog>
    );
}

/** One of a few choices, a pill each in one pill: which computer the command is for, or whether agents run apps. */
function Segmented<T extends string>({ label, options, value, onChange, className }: { label: string; options: readonly { id: T; label: string }[]; value: T; onChange: (value: T) => void; className?: string }) {
    return (
        <div role="radiogroup" aria-label={label} className={cn('inline-flex rounded-full bg-foreground/[0.05] p-0.5 ring-1 ring-inset ring-foreground/[0.06]', className)}>
            {options.map((o) => (
                <button
                    key={o.id}
                    type="button"
                    role="radio"
                    aria-checked={value === o.id}
                    onClick={() => onChange(o.id)}
                    className={cn(
                        'h-7 rounded-full px-3 text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        value === o.id ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                    )}
                >
                    {o.label}
                </button>
            ))}
        </div>
    );
}

/** The command as a shell shows it, whole and at the box's full width, wrapped where it must: read before it's run. */
function Command({ command, expired, onCopied }: { command: string; expired: boolean; onCopied: () => void }) {
    const [copied, setCopied] = useState(false);
    useEffect(() => {
        if (!copied) return;
        const timer = window.setTimeout(() => setCopied(false), 1600);
        return () => window.clearTimeout(timer);
    }, [copied]);
    return (
        <div className={cn('mt-2 rounded-[20px] bg-foreground/[0.045] px-4 pb-2.5 pt-3.5 ring-1 ring-inset ring-foreground/[0.06]', expired && 'pb-3.5 opacity-60')}>
            <code data-testid="install-command" className={cn('block font-mono text-[12.5px] leading-[1.65] text-foreground [overflow-wrap:anywhere]', expired && 'line-through decoration-foreground/30')}>
                <span className="select-none text-muted-foreground">$ </span>
                {command}
            </code>
            {!expired && (
                <div className="mt-2 flex justify-end">
                    <button
                        type="button"
                        onClick={() => {
                            void navigator.clipboard?.writeText(command);
                            setCopied(true);
                            onCopied();
                        }}
                        className={cn(copied ? BUTTON_SECONDARY : BUTTON_PRIMARY, 'h-8 shrink-0 gap-1.5 px-3 font-sans text-[12.5px]')}
                    >
                        {copied ? <Check className="h-3.5 w-3.5" strokeWidth={2.25} /> : <Copy className="h-3.5 w-3.5" strokeWidth={1.9} />}
                        {copied ? 'Copied' : 'Copy'}
                    </button>
                </div>
            )}
        </div>
    );
}

/** The few facts that hold whatever step it's at (what it keeps for you is picked above them). */
function Facts({ mac }: { mac: boolean }) {
    const rows: { icon: ReactNode; text: ReactNode }[] = [
        { icon: <Moon className="h-3.5 w-3.5" strokeWidth={1.75} />, text: 'Agents run only while it’s awake: a sleeping laptop counts as offline.' },
        { icon: <CircleDollarSign className="h-3.5 w-3.5" strokeWidth={1.75} />, text: 'Free: no hourly charge, and models at cost.' },
        {
            icon: <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />,
            text: (
                <>
                    To remove it, run <code className="rounded-full bg-foreground/[0.06] px-1.5 py-px font-mono text-[11.5px] text-foreground/85 [overflow-wrap:anywhere]">{mac ? UNINSTALL_MAC : UNINSTALL}</code>. {mac ? 'It takes everything NoClick added.' : 'Docker and gVisor stay.'}
                </>
            ),
        },
    ];
    return (
        <ul className="mt-3 space-y-1.5 border-t border-border pt-4 dark:border-foreground/[0.08]">
            {rows.map((f, i) => (
                <li key={i} className="flex gap-2.5 text-[12.5px] leading-snug text-muted-foreground">
                    <span className="mt-px shrink-0 text-foreground/50">{f.icon}</span>
                    <span>{f.text}</span>
                </li>
            ))}
        </ul>
    );
}
