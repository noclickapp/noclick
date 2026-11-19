// "Move one from your laptop": a prompt to paste into the coding agent session you want to move. It points the agent at
// NoClick's move guide with a one-time code; the agent works out its harness and session and uploads what it chooses,
// and this card follows the move live (platform:resource frames of kind agent_move) from waiting, through what has
// arrived and each step of making the agent, to the agent opening on its moved conversation.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Check, ChevronRight, CircleAlert, Copy, Mail, SquareTerminal, X } from 'lucide-react';
import { AgentMove, type HarnessName, type NoClick } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { useWorkFrames } from '@/sdk/live';
import { HarnessMark, harnessLabel } from '../agents/harness';

/** The harnesses a laptop session can come from, in the order the card shows them. */
const MOVABLE: HarnessName[] = ['claude_code', 'codex', 'opencode', 'hermes', 'openclaw'];

/** A move as the card reads it (POST /v1/agents/moves, GET /v1/agents/moves/{id}). */
export interface Move {
    id: string;
    prompt: string | null;
    expiresAt: Date | null;
    status: 'waiting' | 'moving' | 'finishing' | 'done' | 'failed' | 'canceled' | 'expired';
    source: { harness: HarnessName | null; host: string | null; cwd: string | null; cliVersion: string | null; title: string | null } | null;
    arrived: {
        session: { title: string | null; messages: number } | null;
        repo: { name: string; branch: string | null } | null;
        files: number;
        secrets: string[];
        mcpServers: string[];
        skills: string[];
        memories: string[];
        note: boolean;
    };
    steps: { name: string; label: string | null; status: 'pending' | 'running' | 'done' | 'failed'; detail: string | null; error: string | null }[];
    agentId: string | null;
    conversation: string | null;
    error: string | null;
}

/** The card's view of a move, from the SDK's `AgentMove` (its prompt comes only with the create). */
function viewOf(move: AgentMove, prompt: string | null): Move {
    const source = move.source;
    const a = move.arrived;
    return {
        id: move.id,
        prompt,
        expiresAt: move.expiresAt,
        status: move.status as Move['status'],
        source: source ? { harness: (source.harness || null) as HarnessName | null, host: source.host || null, cwd: source.cwd || null, cliVersion: source.cliVersion, title: source.title } : null,
        arrived: {
            session: a.session ? { title: a.session.title, messages: a.session.messages } : null,
            repo: a.repo ? { name: a.repo.name, branch: a.repo.branch || null } : null,
            files: a.files.length,
            secrets: a.secrets.map((s) => s.name),
            mcpServers: a.mcpServers.map((m) => m.name),
            skills: a.skills.map((m) => m.name),
            memories: a.memories.map((m) => m.name),
            note: !!a.note,
        },
        steps: move.steps.map((step) => ({ name: step.name, label: step.label ?? null, status: step.status, detail: step.detail ?? null, error: step.error ?? null })),
        agentId: move.agentId,
        conversation: move.conversation,
        error: move.error,
    };
}

const createMove = async (client: NoClick, workspaceId: string | null, machine: string | null) => {
    const move = await AgentMove.create({ client, ...(workspaceId ? { workspaceId } : {}), ...(machine ? { machine } : {}) });
    return viewOf(move, move.prompt);
};
const readMove = async (client: NoClick, id: string, prompt: string | null) => viewOf(await AgentMove.fromId(id, { client }).refresh(), prompt);
const cancelMove = (client: NoClick, id: string) => AgentMove.fromId(id, { client }).cancel();

/**
 * Where a move stands for the person: still `open` (waiting for the code, carrying, or refused at a step the agent
 * can fix and finish again while its key lives), `done`, or `ended` (expired, called off, or refused with its time
 * gone). Only an ended move reads as stopped.
 */
export function moveState(move: Pick<Move, 'status' | 'expiresAt'>, now: number = Date.now()): 'open' | 'done' | 'ended' {
    if (move.status === 'done') return 'done';
    if (move.status === 'expired' || move.status === 'canceled') return 'ended';
    if (move.status === 'failed' && move.expiresAt !== null && move.expiresAt.getTime() <= now) return 'ended';
    return 'open';
}

/** The card's heading and the line under it. */
export function moveHeading(move: Pick<Move, 'status' | 'expiresAt'>, now: number = Date.now()): { title: string; line: string | null } {
    const state = moveState(move, now);
    if (state === 'done') return { title: 'Moved', line: null };
    if (state === 'ended')
        return {
            title: 'The move stopped',
            line: move.status === 'canceled' ? 'It was called off.' : 'Its time ran out before it finished. Get a new code to move it again.',
        };
    if (move.status === 'failed') return { title: 'Waiting on your agent', line: 'It was told what to fix, and finishes again once it has.' };
    return { title: 'Moving it in', line: null };
}

const STEP_LABEL: Record<string, string> = {
    secrets: 'Bringing its secrets',
    agent: 'Making the agent',
    space: 'Adding it to this space',
    files: 'Saving its files',
    tools: 'Connecting its tools',
    skills: 'Bringing its skills',
    memories: 'Bringing its memory',
    conversation: 'Bringing the conversation',
};

/** Below 640px: the phone's layout. */
function useNarrow() {
    const [narrow, setNarrow] = useState(false);
    useEffect(() => {
        const query = window.matchMedia('(max-width: 639px)');
        const update = () => setNarrow(query.matches);
        update();
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, []);
    return narrow;
}

function SlowRing() {
    return <span aria-hidden className="work-spin h-3.5 w-3.5 shrink-0 rounded-full border-2 border-foreground/15 border-t-foreground/70" style={{ animationDuration: '2.4s' }} />;
}

/** The five harness marks a laptop session can come from, overlapping a little. */
function MovableMarks() {
    return (
        <span className="flex items-center -space-x-1" aria-label={`From ${MOVABLE.map(harnessLabel).join(', ')}`}>
            {MOVABLE.map((h) => (
                <span key={h} className="grid h-6 w-6 place-items-center rounded-full bg-background ring-2 ring-background dark:bg-[hsl(var(--composer))]">
                    <HarnessMark harness={h} className="h-3.5 w-3.5" />
                </span>
            ))}
        </span>
    );
}

const CARD = 'w-full rounded-[26px] bg-composer text-left shadow-[0_18px_48px_-24px_rgba(0,0,0,0.35)] ring-1 ring-inset ring-border dark:ring-foreground/[0.09]';
const CIRCLE = 'grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground';
const QUIET = 'rounded-full underline decoration-muted-foreground/40 underline-offset-2 transition-colors hover:text-foreground hover:decoration-foreground/60';

/** A pill under the draft's box; opened, one prompt to copy into the session, then the move as it happens. The moved
 * agent runs where the draft's Runs in says: a sandbox, or `machineId`. */
export function MoveCard({ spaceId, machineId, onMoved }: { spaceId: string | null; machineId: string | null; onMoved: (agentId: string) => void }) {
    const client = useWorkClient();
    const phone = useNarrow();
    const [open, setOpen] = useState(false);
    const [move, setMove] = useState<Move | null>(null);
    const [copied, setCopied] = useState(false);
    const [waiting, setWaiting] = useState(false);
    const [, tick] = useState(0);
    const begin = async () => {
        try {
            setMove(await createMove(client, spaceId, machineId));
            setCopied(false);
            setWaiting(false);
        } catch (error) {
            toast('Couldn’t start a move', { description: error instanceof Error ? error.message : String(error) });
            setOpen(false);
        }
    };
    const reread = async () => {
        if (!move) return;
        try {
            // The prompt and code come only with the create.
            setMove(await readMove(client, move.id, move.prompt));
        } catch {
            // A slow re-read follows; a frame reads it again.
        }
    };
    useWorkFrames('platform:resource', (frame) => {
        const kind: string = frame.kind;
        if (kind === 'agent_move' && frame.id === move?.id) void reread();
    });
    // The backstop for a missed frame, and the minutes left on the code.
    useEffect(() => {
        if (!move || moveState(move) !== 'open') return;
        const timer = window.setInterval(() => {
            tick((n) => n + 1);
            if (document.visibilityState === 'visible') void reread();
        }, 30_000);
        return () => window.clearInterval(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [move?.id, move?.status]);
    useEffect(() => {
        if (move?.status === 'done' && move.agentId) onMoved(move.agentId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [move?.status]);
    useEffect(() => {
        if (!copied) return;
        const t = setTimeout(() => setCopied(false), 1800);
        return () => clearTimeout(t);
    }, [copied]);

    const close = () => {
        if (move && moveState(move) === 'open') void cancelMove(client, move.id).catch(() => undefined);
        setOpen(false);
        setMove(null);
    };

    if (!open)
        return (
            <button
                type="button"
                onClick={() => {
                    setOpen(true);
                    void begin();
                }}
                className={cn(BUTTON_SECONDARY, 'group h-12 w-full max-w-[30rem] justify-start gap-3 pl-2 pr-4 text-[14px] max-sm:max-w-none')}
            >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-background text-foreground dark:bg-foreground/[0.08]">
                    <SquareTerminal className="h-4 w-4" strokeWidth={1.75} />
                </span>
                <span className="min-w-0 flex-1 truncate text-left">Move one from your laptop</span>
                {/* A phone keeps the room for the words; the agents that move show on the card it opens. */}
                <span className="contents max-md:hidden">
                    <MovableMarks />
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
            </button>
        );

    // A code that expired before any agent used it stays on the prompt card, with a new code a tap away.
    const unused = move?.status === 'expired' && !move.source && !move.arrived.session;
    if (move && move.status !== 'waiting' && !unused) return <Moving move={move} onCancel={close} />;

    const minutesLeft = move?.expiresAt ? Math.max(0, Math.ceil((move.expiresAt.getTime() - Date.now()) / 60_000)) : null;
    const copy = () => {
        if (!move?.prompt) return;
        void navigator.clipboard?.writeText(move.prompt);
        setCopied(true);
        setWaiting(true);
    };
    return (
        <div className={cn(CARD, 'max-w-[30rem] p-4 pt-3.5 max-sm:max-w-none')} data-testid="move-card">
            <div className="flex items-center gap-3">
                <span className="min-w-0 flex-1 pl-1 text-[14.5px] font-medium">Move one from your laptop</span>
                <span className="max-sm:hidden">
                    <MovableMarks />
                </span>
                <button type="button" onClick={close} aria-label="Close" className={CIRCLE}>
                    <X className="h-4 w-4" strokeWidth={1.75} />
                </button>
            </div>
            <p className="mt-0.5 flex items-center justify-between gap-3 pl-1 text-[13px] text-muted-foreground">
                Copy and paste this prompt.
                <span className="sm:hidden">
                    <MovableMarks />
                </span>
            </p>
            <div className="mt-3.5 flex gap-2 max-sm:flex-col">
                <button type="button" disabled={!move?.prompt} onClick={copy} className={cn(BUTTON_PRIMARY, 'max-sm:justify-center')}>
                    {copied ? <Check className="h-4 w-4" strokeWidth={2.25} /> : <Copy className="h-4 w-4" strokeWidth={1.75} />}
                    {copied ? 'Copied' : 'Copy prompt'}
                </button>
                {phone && move?.prompt && (
                    <a href={`mailto:?subject=${encodeURIComponent('Move this session to NoClick')}&body=${encodeURIComponent(move.prompt)}`} onClick={() => setWaiting(true)} className={cn(BUTTON_SECONDARY, 'justify-center')}>
                        <Mail className="h-4 w-4" strokeWidth={1.75} />
                        Send it to myself
                    </a>
                )}
            </div>
            {(waiting || unused) && (
                <div className={cn('mt-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t px-1 pt-3 text-[12.5px] text-muted-foreground', HAIRLINE)}>
                    <SlowRing />
                    <span className="text-foreground/85">{move?.status === 'expired' ? 'The code expired.' : 'Waiting for your agent…'}</span>
                    {minutesLeft !== null && move?.status !== 'expired' && <span className="tabular-nums">Code expires in {minutesLeft} min</span>}
                    <button
                        type="button"
                        onClick={() => {
                            if (move) void cancelMove(client, move.id).catch(() => undefined);
                            void begin().then(() => toast('New code', { description: 'Copy the prompt again: the old one stopped working.' }));
                        }}
                        className={QUIET}
                    >
                        Get a new code
                    </button>
                </div>
            )}
        </div>
    );
}

/** The move once the agent has the code: where it's from, what has arrived, then each step of making the agent. */
function Moving({ move, onCancel }: { move: Move; onCancel: () => void }) {
    const s = move.source;
    const a = move.arrived;
    const arrived: string[] = [
        a.session ? `the conversation${a.session.title ? ` ‘${a.session.title}’` : ''} · ${a.session.messages} messages` : '',
        a.repo ? `${a.repo.name}${a.repo.branch ? ` · ${a.repo.branch}` : ''}` : '',
        a.files ? `${a.files} ${a.files === 1 ? 'file' : 'files'}` : '',
        a.secrets.length ? `${a.secrets.length} secrets (${a.secrets.join(', ')})` : '',
        a.mcpServers.length ? `MCP servers: ${a.mcpServers.join(', ')}` : '',
        a.skills.length ? `skills: ${a.skills.join(', ')}` : '',
        a.memories.length ? `${a.memories.length} memories` : '',
        a.note ? 'a note on where it left off' : '',
    ].filter(Boolean);
    const state = moveState(move);
    // A refusal the agent can still fix reads as what it's fixing, not as an error.
    const fixing = state === 'open' && move.status === 'failed';
    const heading = moveHeading(move);
    return (
        <div className={cn(CARD, 'max-w-[38rem] max-sm:max-w-none')} data-testid="move-progress">
            <div className="px-5 pb-3 pt-4">
                <p className="text-[15px] font-medium">{heading.title}</p>
                {heading.line && <p className="mt-0.5 text-[12.5px] text-muted-foreground">{heading.line}</p>}
                {s && (
                    <p className="mt-1 flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                        {s.harness && <HarnessMark harness={s.harness} className="h-3.5 w-3.5" />}
                        <span className="truncate">{[s.host, s.cwd, s.harness ? `${harnessLabel(s.harness)}${s.cliVersion ? ` ${s.cliVersion}` : ''}` : null].filter(Boolean).join(' · ')}</span>
                    </p>
                )}
            </div>
            {arrived.length > 0 && (
                <ul className={cn('border-t px-5 py-2.5 text-[13px]', HAIRLINE)} aria-label="What has arrived">
                    {arrived.map((line) => (
                        <li key={line} className="flex items-center gap-2 py-1">
                            <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2.25} />
                            {line}
                        </li>
                    ))}
                </ul>
            )}
            {move.steps.length > 0 && (
                <ul className={cn('border-t px-5 py-2', HAIRLINE)} aria-label="Steps">
                    {move.steps.map((step) => (
                        <li key={step.name} className="py-2">
                            <div className="flex items-center gap-3">
                                <span className="grid h-5 w-5 shrink-0 place-items-center">
                                    {step.status === 'done' ? (
                                        <Check className="h-4 w-4 text-foreground" strokeWidth={2.25} />
                                    ) : step.status === 'running' ? (
                                        <span aria-hidden className="work-spin h-3.5 w-3.5 rounded-full border-2 border-foreground/15 border-t-foreground/80" />
                                    ) : step.status === 'failed' && fixing ? (
                                        <SlowRing />
                                    ) : step.status === 'failed' ? (
                                        <CircleAlert className="h-4 w-4 text-red-600 dark:text-red-400" strokeWidth={2} />
                                    ) : (
                                        <span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-foreground/15" />
                                    )}
                                </span>
                                <span className={cn('flex-1 text-[14px]', step.status === 'pending' && 'text-muted-foreground')}>
                                    {step.label ?? STEP_LABEL[step.name] ?? step.name}
                                    {step.detail && <span className="text-muted-foreground"> · {step.detail}</span>}
                                </span>
                            </div>
                            {step.error && <p className={cn('ml-8 mt-1.5 text-[12.5px] leading-snug', fixing ? 'text-muted-foreground' : 'text-red-600 dark:text-red-400')}>{step.error}</p>}
                        </li>
                    ))}
                </ul>
            )}
            {move.error && !move.steps.some((step) => step.error === move.error) && (
                <p className={cn('border-t px-5 py-3 text-[12.5px]', HAIRLINE, fixing ? 'text-muted-foreground' : 'text-red-600 dark:text-red-400')}>{move.error}</p>
            )}
            <div className={cn('flex items-center gap-3 border-t px-5 py-3', HAIRLINE)}>
                <p className="min-w-0 flex-1 text-[12.5px] text-muted-foreground">Your laptop keeps its files, its session and its sign-in.</p>
                {state !== 'done' && (
                    <button type="button" onClick={onCancel} className={BUTTON_SECONDARY.replace('h-9', 'h-8').replace('px-4', 'px-3')}>
                        {state === 'ended' ? 'Close' : 'Cancel'}
                    </button>
                )}
            </div>
        </div>
    );
}
