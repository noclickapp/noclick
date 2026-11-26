// The conversation's rows, t3code's CLI chat in NoClick's one message look (the Chat page draws them too): your
// messages as bubbles on the right (a teammate's under their name), the agent's words in the lane in the app's own
// markdown at 15px, each turn's work as its activity log above its reply, what its harness asks you as a work-log row
// you answer in place, and the files a turn changed as a card under it; a message's time and Copy on hover.
import { useEffect, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ArrowUpRight, Bot, Check, CircleHelp, Copy, EyeOff, FileDiff, FilePen, FileText, GitBranch, KeyRound, ListChecks, Minimize2, MoreHorizontal, Paperclip, Pencil, Redo2, RotateCw, ShieldAlert, ShieldCheck, SquareTerminal, Wallet, Wrench, type LucideIcon } from 'lucide-react';
import type { AgentStepDiff, HarnessRequest, RequestDecision } from 'noclick';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import { DiffStat, StepList, SystemDivider, WorkFold, WorkingLine, diffStat, failedStep, type ToolCalls } from './Activity';
import { useModelAccounts } from '../newAgent/catalog';
import { clockOf, XS_BUTTON, XS_GHOST, XS_OUTLINE } from './styles';
import { changedFiles, stepsOf, type Failure, type MarkerEntry, type NoteEntry, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import { TURN_FAILED_LINE } from '@/lib/agentThread/messages';
import { PlanLimitLine } from './ModelSwitch';
import { useSlot } from '@/slots';
import { REPLY_MARKDOWN } from '../slots';

/** Words as every conversation renders them: whoever shows Work's Markdown (`REPLY_MARKDOWN`) at 15px; a person's
 *  keep their line breaks. */
export function Words({ text, muted, breaks }: { text: string; muted?: boolean; breaks?: boolean }) {
    const MarkdownRenderer = useSlot(REPLY_MARKDOWN);
    return <MarkdownRenderer content={text} breaks={breaks} className={cn('text-[15px] leading-relaxed', muted ? 'text-muted-foreground [&_p]:text-muted-foreground' : 'text-foreground')} />;
}

function useCopy(text: string) {
    const [copied, setCopied] = useState(false);
    useEffect(() => {
        if (!copied) return;
        const t = setTimeout(() => setCopied(false), 1500);
        return () => clearTimeout(t);
    }, [copied]);
    const copy = () =>
        navigator.clipboard.writeText(text).then(
            () => setCopied(true),
            () => toast('Couldn’t copy', { description: 'The browser refused the clipboard.' })
        );
    return { copied, copy };
}

const META_ICON =
    'max-md:-m-2 max-md:h-10 max-md:w-10 grid h-6 w-6 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 disabled:pointer-events-none';

/** A message's time and what you can do with it, t3code's: under your bubble the time, Edit from here and Copy; under
 *  the agent's reply Copy and the time. Shown on hover or focus (always on touch), in place so nothing moves. */
export function MessageMeta({ end, at, text, onRewind }: { end: boolean; at: number; text: string; onRewind?: () => void }) {
    const { copied, copy } = useCopy(text);
    const stamp = (
        <ShortcutTooltip label={new Date(at).toLocaleString()}>
            <time className="text-xs tabular-nums text-muted-foreground" dateTime={new Date(at).toISOString()}>
                {clockOf(at)}
            </time>
        </ShortcutTooltip>
    );
    const copyButton = (
        <ShortcutTooltip label="Copy message">
            <button type="button" aria-label="Copy message" disabled={copied} onClick={copy} className={META_ICON}>
                <span key={String(copied)} className="wc-swap grid place-items-center">
                    {copied ? <Check className="h-3 w-3 text-foreground" strokeWidth={2.25} /> : <Copy className="h-3 w-3" strokeWidth={2} />}
                </span>
            </button>
        </ShortcutTooltip>
    );
    return (
        <div className={cn('flex items-center gap-2 opacity-0 transition-opacity duration-200 focus-within:opacity-100 group-hover:opacity-100 [@media(pointer:coarse)]:opacity-100', end ? 'justify-end pe-1' : 'mt-1.5')}>
            {end ? (
                <>
                    {stamp}
                    <span className="flex items-center gap-0.5">
                        {onRewind && (
                            <ShortcutTooltip label="Edit from here">
                                <button type="button" aria-label="Edit from here" onClick={onRewind} className={META_ICON}>
                                    <Pencil className="h-3 w-3" strokeWidth={2} />
                                </button>
                            </ShortcutTooltip>
                        )}
                        {copyButton}
                    </span>
                </>
            ) : (
                <>
                    {copyButton}
                    {stamp}
                </>
            )}
        </div>
    );
}

/** Files a message carried: pictures as thumbnails, anything else as a card. */
function SentFiles({ files }: { files: UserEntry['files'] }) {
    if (!files.length) return null;
    return (
        <div className="flex max-w-[80%] flex-wrap justify-end gap-1.5">
            {files.map((f) =>
                f.kind === 'image' ? (
                    <a key={f.url} href={f.url} target="_blank" rel="noopener noreferrer">
                        <img src={f.url} alt={f.name} className="h-24 max-w-[200px] rounded-2xl object-cover ring-1 ring-inset ring-foreground/[0.08]" />
                    </a>
                ) : (
                    <a key={f.url} href={f.url} target="_blank" rel="noopener noreferrer" className="flex h-9 max-w-[240px] items-center gap-2 rounded-2xl bg-foreground/[0.06] px-3 text-xs text-foreground/85">
                        <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                        <span className="truncate">{f.name}</span>
                    </a>
                )
            )}
        </div>
    );
}

/** Whether a message holds code or a line too long to wrap (test output, a path): its bubble may take the whole lane,
 *  so code isn't cut at 80%. The bubble is only ever as wide as what it holds. */
export const holdsCode = (text: string) => text.includes('```') || /\S{48,}/.test(text);

/** A person's message: your own a bubble on the right; anyone else's (a teammate, the account's owner, another agent)
 *  under their name; a harness command a bubble with its line; a steer marked as such. */
/** A person's message, on the right. One written for a subagent says so in main's thread; in that subagent's own log
 *  (`receipt`) it says instead how it got there. `source`: where it came from, when not the session's own box. */
export function UserRow({ entry, mine, onRewind, compact, receipt, chips, source }: { entry: UserEntry; mine: boolean; onRewind?: () => void; compact?: boolean; receipt?: ReactNode; chips?: ReactNode; source?: ReactNode }) {
    const other = !mine;
    const text = entry.command ? `/${entry.command.name}${entry.command.arguments ? ` ${entry.command.arguments}` : ''}` : entry.text;
    return (
        <div className={cn('group flex flex-col items-end gap-1 px-1', compact ? 'pt-2' : 'pt-4')} data-row="user" data-pending={entry.pending || undefined}>
            {entry.subagent && !receipt ? (
                <p className="me-1 flex max-w-[80%] items-center gap-1 text-xs text-muted-foreground" data-for-subagent={entry.subagent.id}>
                    <Bot className="h-3 w-3 shrink-0" strokeWidth={2} />
                    <span className="truncate">For its subagent “{entry.subagent.title}”</span>
                </p>
            ) : entry.steer && !receipt && (
                <p className="me-1 flex items-center gap-1 text-xs text-muted-foreground">
                    <Redo2 className="h-3 w-3" strokeWidth={2} />
                    Steer
                </p>
            )}
            {other && (
                <p className="me-1 text-[11px] leading-4 text-fuchsia-600 dark:text-fuchsia-300">
                    {entry.author?.name ?? 'Someone'}
                    <span className="sr-only"> wrote</span>
                </p>
            )}
            {!other && entry.via && <p className="me-1 text-[11px] leading-4 text-muted-foreground">by {entry.via === 'call' ? 'phone' : entry.via === 'imessage' ? 'iMessage' : entry.via === 'whatsapp' ? 'WhatsApp' : 'email'}</p>}
            {source && <div className="me-1 flex max-w-[80%] justify-end">{source}</div>}
            <SentFiles files={entry.files} />
            {chips && <div className="flex max-w-[80%] flex-wrap justify-end gap-1.5">{chips}</div>}
            {entry.command ? (
                <div className="flex max-w-[80%] items-center gap-2 rounded-2xl rounded-br-sm bg-secondary px-3.5 py-2">
                    <SquareTerminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                    <code className="min-w-0 font-mono text-xs text-foreground [overflow-wrap:anywhere]">{text}</code>
                </div>
            ) : (
                text && (
                    <div className={cn(holdsCode(text) ? 'max-w-full' : 'max-w-[80%]', 'rounded-2xl rounded-br-sm px-4 py-2.5 text-foreground', other ? 'bg-fuchsia-500/[0.12] dark:bg-fuchsia-400/[0.1]' : 'bg-secondary', entry.pending && 'opacity-70')} data-bubble>
                        <Words text={text} breaks />
                    </div>
                )
            )}
            {receipt ?? (text && <MessageMeta end at={entry.at} text={text} onRewind={onRewind} />)}
        </div>
    );
}

/** What started a turn no person sent: "Triggered by" a schedule or an event, a wake-up it set, or a run of a loop;
 *  `onOpen` opens it in the agent's Triggers tab. A wake-up's title is the agent's own note of why it set it, a loop's
 *  its prompt, any length: it reads under the divider, wrapped. */
export function TriggerRow({ entry, onOpen }: { entry: UserEntry; onOpen?: () => void }) {
    const kind = entry.trigger?.kind;
    const wakeup = kind === 'wakeup' || kind === 'loop';
    const what = kind === 'loop' ? 'A run of its loop' : wakeup ? 'A wake-up it set' : `Triggered by ${entry.trigger?.title || (kind === 'cron' ? 'its schedule' : 'an event')}`;
    const why = wakeup ? entry.trigger?.title : null;
    const label = onOpen ? (
        <button type="button" onClick={onOpen} className="underline-offset-2 hover:text-foreground hover:underline">
            {what}
        </button>
    ) : (
        what
    );
    return (
        <div data-row="trigger">
            <SystemDivider label={label} detail={clockOf(entry.at)} />
            {why && <p className="-mt-1 px-1 pb-1 text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{why}</p>}
        </div>
    );
}

export function NoteRow({ entry }: { entry: NoteEntry }) {
    return (
        <div className="px-1 pt-4">
            <p className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <EyeOff className="h-3 w-3" strokeWidth={2} />
                A note in the conversation
            </p>
            <Words text={entry.text} muted />
        </div>
    );
}

export function MarkerRow({ entry }: { entry: MarkerEntry }) {
    return <SystemDivider icon={entry.marker === 'compacted' ? Minimize2 : undefined} label={entry.text} />;
}

/** A turn: its work (live, or folded once done), what it said, a message that joined it, what it changed, and what
 *  its harness waits on you for. */
export function TurnView({
    turn,
    mode,
    requests,
    onAnswer,
    onChanges,
    onRewind,
    onReconnect,
    mine,
    cards,
    failureTold,
}: {
    turn: TurnEntry;
    /** A line beside it already says why it failed (a model switch's). */
    failureTold?: boolean;
    /** The cards its calls of NoClick's tools draw (a held purchase, an account to connect), under what it said. */
    cards?: ReactNode;
    mode: ToolCalls;
    /** Whether the person reading wrote a message (a steer), which they can go back to. */
    mine: (entry: UserEntry) => boolean;
    /** What this turn's harness asks you, still waiting or answered. */
    requests: HarnessRequest[];
    onAnswer: (request: HarnessRequest, decision: RequestDecision) => void;
    onChanges?: () => void;
    onRewind?: (entry: UserEntry) => void;
    /** Connects again the account a failed turn's provider refused. */
    onReconnect?: (failure: Failure) => void;
}) {
    const running = turn.status === 'running';
    const steps = stepsOf(turn);
    const files = changedFiles(turn);
    const live = running && (
        <div className="px-1 pb-2 pt-1">
            {turn.parts.map((p, i) =>
                p.kind === 'steps' ? (
                    (() => {
                        const shown = mode === 'all' ? p.steps : mode === 'failures' ? p.steps.filter((s) => s.running || failedStep(s)) : [];
                        return shown.length ? <StepList key={i} steps={shown} groups={mode === 'all' ? turn.groups : []} live className="mt-1" /> : null;
                    })()
                ) : p.kind === 'text' ? (
                    <div key={i} className="py-1.5">
                        <Words text={p.text} />
                    </div>
                ) : (
                    <UserRow key={p.entry.key} entry={p.entry} mine={mine(p.entry)} compact />
                )
            )}
        </div>
    );
    const steers = turn.parts.filter((p) => p.kind === 'user');
    return (
        <div className="group" data-row="turn" data-status={turn.status}>
            {running ? (
                <>
                    {live}
                    {cards && <div className="px-1 pb-2">{cards}</div>}
                    {/* Last, as a terminal's is: where the turn is now, beside the box, however long its work runs. */}
                    <div className="px-1 pb-2">
                        <WorkingLine from={turn.startedAt} compacting={turn.compacting} downloading={turn.downloading} pace={turn.pace} />
                    </div>
                </>
            ) : (
                <div className="px-1 pt-3">
                    <WorkFold steps={steps} ms={(turn.endedAt ?? turn.startedAt) - turn.startedAt} stopped={turn.status === 'stopped'} mode={mode} groups={turn.groups} summary={turn.summary} onChanges={onChanges} />
                    {steers.map((p) => p.kind === 'user' && <UserRow key={p.entry.key} entry={p.entry} mine={mine(p.entry)} compact onRewind={onRewind && mine(p.entry) && p.entry.id ? () => onRewind(p.entry) : undefined} />)}
                    {turn.failure ? (
                        <>
                            {/* What it said on the way, never the platform's line its failed reply carries. */}
                            {turn.reply && turn.reply !== TURN_FAILED_LINE && (
                                <div className="pt-2" data-reply>
                                    <Words text={turn.reply} />
                                </div>
                            )}
                            <RefusedNote failure={turn.failure} told={failureTold} onReconnect={onReconnect} />
                        </>
                    ) : (
                        turn.reply && (
                            <div className="pt-2" data-reply>
                                <Words text={turn.reply} muted={turn.status === 'failed'} />
                            </div>
                        )
                    )}
                    {cards}
                    {/* A turn the platform summed up says what it changed in its fold. */}
                    {files.length > 0 && !turn.summary?.changed && <ChangesCard files={files} onOpen={onChanges} />}
                    {turn.reply && !turn.failure && <MessageMeta end={false} at={turn.endedAt ?? turn.startedAt} text={turn.reply} />}
                </div>
            )}
            {requests.map((r) => (
                <div key={r.id} className="px-1 pb-2">
                    {r.kind === 'question' ? <QuestionSummary request={r} /> : r.action === 'plan' ? <PlanCard request={r} onAnswer={onAnswer} /> : <ApprovalRow request={r} onAnswer={onAnswer} />}
                </div>
            ))}
        </div>
    );
}

// A plan's sign-in is named for its product, not its company.
const PLAN_NAMES: Record<string, string> = { anthropic: 'Claude', openai: 'ChatGPT' };

/** A turn whose model connection's provider turned it down, said as what happened ("OpenRouter refused this agent's
 *  key", "Your ChatGPT sign-in ended", "OpenRouter's account is out of credit"), the provider's own words in a line
 *  where it gave any, and what to do: connect it again, or add funds at the provider (else use another key). A plan at
 *  its limit is no refusal: one quiet line in the platform's words, where no line beside it (`told`) says so already. */
export function RefusedNote({ failure, told, onReconnect, className }: { failure: Failure; told?: boolean; onReconnect?: (failure: Failure) => void; className?: string }) {
    if (failure.reason === 'plan_limit') return told || !failure.message ? null : <PlanLimitLine message={failure.message} className={className} />;
    return <Refusal failure={failure} onReconnect={onReconnect} className={className} />;
}

function Refusal({ failure, onReconnect, className }: { failure: Failure; onReconnect?: (failure: Failure) => void; className?: string }) {
    const { labels } = useModelAccounts();
    const plan = failure.reason === 'signed_out';
    const funds = failure.reason === 'provider_out_of_funds';
    const integration = failure.integration ?? failure.provider;
    const provider = (integration && (plan ? PLAN_NAMES[integration] : labels.get(integration))) || failure.connectionName || 'Its provider';
    const headline = funds ? `${provider}’s account is out of credit` : plan ? `Your ${provider} sign-in ended` : `${provider} refused this agent’s key`;
    const Icon = funds ? Wallet : KeyRound;
    return (
        <div className={cn('pt-2', className)} data-testid="refused-turn">
            <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Icon className="h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-400" strokeWidth={2} />
                {headline}
            </p>
            {failure.providerSaid && (
                <p className="pt-1 text-[13px] leading-relaxed text-muted-foreground">
                    {provider} said “{failure.providerSaid}”
                </p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1">
                {funds && failure.billingUrl && (
                    <a href={failure.billingUrl} target="_blank" rel="noopener noreferrer" className={cn(XS_BUTTON, XS_OUTLINE, 'gap-1.5 px-3')}>
                        Add funds at {provider}
                        <ArrowUpRight className="h-3 w-3" strokeWidth={2.25} />
                    </a>
                )}
                {onReconnect &&
                    (funds ? (
                        <button type="button" onClick={() => onReconnect(failure)} className={cn(XS_BUTTON, XS_GHOST, 'px-3')}>
                            Use another key
                        </button>
                    ) : (
                        <button type="button" onClick={() => onReconnect(failure)} className={cn(XS_BUTTON, XS_OUTLINE, 'gap-1.5 px-3')}>
                            <RotateCw className="h-3 w-3" strokeWidth={2.25} />
                            {plan ? 'Sign in again' : `Reconnect ${provider}`}
                        </button>
                    ))}
            </div>
        </div>
    );
}

const ACTION_ICON: Record<string, LucideIcon> = { command: SquareTerminal, edit: FilePen, read: FileText, fetch: FileText, tool: Wrench, plan: ListChecks, push: GitBranch };

const DECISION_WORDS: Record<string, string> = { allow_once: 'Approved', allow_always: 'Always allowed this session', reject_once: 'Declined', cancel: 'Canceled' };

/** What became of a request once it ended. */
function outcomeOf(request: HarnessRequest): string {
    if (request.status === 'expired') return 'Nobody answered in time: declined';
    if (request.status === 'canceled') return 'Its turn stopped';
    const decision = typeof request.answer?.decision === 'string' ? request.answer.decision : '';
    const note = typeof request.answer?.note === 'string' && request.answer.note ? `, with your reply: “${request.answer.note}”` : '';
    return (DECISION_WORDS[decision] ?? 'Answered') + note;
}

const LINK = 'rounded-full underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';

/** An approval its harness waits on, as t3code shows one: what it wants and the command or file, then "Waiting for
 *  approval · Decline · Approve · More" (Always allow this session, Cancel). A subagent's names it. */
export function ApprovalRow({ request, onAnswer }: { request: HarnessRequest; onAnswer: (request: HarnessRequest, decision: RequestDecision) => void }) {
    const Icon = ACTION_ICON[request.action ?? 'tool'] ?? Wrench;
    const title = request.title ?? 'Act';
    const what = title.charAt(0).toLowerCase() + title.slice(1);
    const by = typeof request.raw.by === 'string' && request.raw.by ? 'A subagent wants to' : 'Wants to';
    const always = request.options.some((o) => o.kind === 'allow_always');
    const reason = typeof request.raw.reason === 'string' ? request.raw.reason : '';
    const pending = request.status === 'pending';
    return (
        <div data-approval={request.action ?? 'tool'} className="mt-2">
            <p className="flex min-h-6 items-start gap-1.5 text-sm leading-6">
                <span className="grid h-6 w-6 shrink-0 place-items-center">
                    <Icon className="h-4 w-4 text-muted-foreground/80" strokeWidth={2} />
                </span>
                <span className="min-w-0 [overflow-wrap:anywhere]">
                    <span className="text-muted-foreground">{by}</span> <span className="text-foreground/90">{what}</span>
                </span>
            </p>
            {request.detail && request.detail !== title && <code className="ml-7 mt-0.5 block max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs leading-5 text-foreground">{request.detail}</code>}
            {reason && <p className="ml-7 mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">{reason}</p>}
            <p className="ml-7 mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                {pending ? (
                    <>
                        <ShieldAlert className="h-3 w-3 text-foreground" strokeWidth={2} />
                        <span className="text-foreground">Waiting for approval</span>
                        <span aria-hidden>·</span>
                        <button type="button" onClick={() => onAnswer(request, 'reject_once')} className={LINK}>
                            Decline
                        </button>
                        <span aria-hidden>·</span>
                        <button type="button" onClick={() => onAnswer(request, 'allow_once')} className={cn(LINK, 'font-medium text-foreground')}>
                            Approve
                        </button>
                        <span aria-hidden>·</span>
                        <DropdownMenu>
                            <DropdownMenuTrigger aria-label="More approval options" className={LINK}>
                                More
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start" sideOffset={6} className={cn('work-rise w-[220px] rounded-2xl p-1', MENU_SURFACE)}>
                                {always && (
                                    <DropdownMenuItem onSelect={() => onAnswer(request, 'allow_always')} className="min-h-7 rounded-xl px-2 py-1 text-sm">
                                        Always allow this session
                                    </DropdownMenuItem>
                                )}
                                <DropdownMenuItem onSelect={() => onAnswer(request, 'cancel')} className="min-h-7 rounded-xl px-2 py-1 text-sm">
                                    Cancel the turn
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </>
                ) : (
                    <>
                        <ShieldCheck className="h-3 w-3" strokeWidth={2} />
                        {outcomeOf(request)}
                    </>
                )}
            </p>
        </div>
    );
}

/** A plan the agent proposes (Claude Code leaving plan mode with it), t3code's card: "Plan", its text, and your go
 *  under it. Past twenty lines it folds behind Expand plan. */
export function PlanCard({ request, onAnswer }: { request: HarnessRequest; onAnswer: (request: HarnessRequest, decision: RequestDecision) => void }) {
    const plan = request.plan ?? '';
    const long = plan.split('\n').length > 20 || plan.length > 900;
    const [open, setOpen] = useState(!long);
    const { copy } = useCopy(plan);
    const pending = request.status === 'pending';
    return (
        <div data-plan className="mt-3 rounded-[26px] border border-border bg-foreground/[0.02] p-4 dark:border-foreground/[0.08] sm:p-5">
            <div className="flex items-center gap-2">
                <span className="shrink-0 rounded-full bg-foreground/[0.07] px-2 py-0.5 text-[11px] font-medium leading-4 text-foreground/80">Plan</span>
                <p className="min-w-0 flex-1 truncate text-sm font-medium">{plan.split('\n').find((l) => l.trim())?.replace(/^#+\s*/, '') ?? 'Its plan'}</p>
                <DropdownMenu>
                    <DropdownMenuTrigger aria-label="Plan actions" className={cn(XS_BUTTON, XS_OUTLINE, 'h-6 w-6 px-0')}>
                        <MoreHorizontal className="h-3.5 w-3.5" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" sideOffset={6} className={cn('work-rise w-[220px] rounded-2xl p-1', MENU_SURFACE)}>
                        <DropdownMenuItem onSelect={copy} className="min-h-7 gap-2 rounded-xl px-2 py-1 text-sm">
                            <Copy className="h-4 w-4 opacity-80" strokeWidth={2} />
                            Copy to clipboard
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            <div className={cn('relative mt-3 text-sm', !open && 'max-h-[26rem] overflow-hidden')}>
                <Words text={plan} />
                {!open && <div aria-hidden className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-background to-transparent" />}
            </div>
            {long && (
                <button type="button" onClick={() => setOpen(!open)} className={cn(XS_BUTTON, XS_GHOST, 'mx-auto mt-2 flex')}>
                    {open ? 'Collapse plan' : 'Expand plan'}
                </button>
            )}
            <div className="-mx-4 mt-4 border-t border-border px-4 pt-3 dark:border-foreground/[0.08] sm:-mx-5 sm:px-5">
                <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                    {pending ? (
                        <>
                            <ShieldAlert className="h-3 w-3 text-foreground" strokeWidth={2} />
                            <span className="text-foreground">Waiting for your go</span>
                            <span aria-hidden>·</span>
                            <button type="button" onClick={() => onAnswer(request, 'reject_once')} className={LINK}>
                                Keep planning
                            </button>
                            <span aria-hidden>·</span>
                            <button type="button" onClick={() => onAnswer(request, 'allow_once')} className={cn(LINK, 'font-medium text-foreground')}>
                                Approve and build
                            </button>
                        </>
                    ) : (
                        <>
                            <ShieldCheck className="h-3 w-3" strokeWidth={2} />
                            {outcomeOf(request)}
                        </>
                    )}
                </p>
            </div>
        </div>
    );
}

/** A question it asked, as it stands in the conversation; you answer in the panel over the box. */
export function QuestionSummary({ request }: { request: HarnessRequest }) {
    const first = request.questions[0];
    const prompt = typeof first?.question === 'string' ? first.question : 'A question';
    return (
        <div className="mt-2" data-question>
            <p className="flex min-h-6 items-start gap-1.5 text-sm leading-6">
                <span className="grid h-6 w-6 shrink-0 place-items-center">
                    <CircleHelp className="h-4 w-4 text-muted-foreground/80" strokeWidth={2} />
                </span>
                <span className="min-w-0 text-foreground/90 [overflow-wrap:anywhere]">{prompt}</span>
            </p>
            <p className="ml-7 text-xs text-muted-foreground">{request.status === 'pending' ? 'Waiting for your answer, over the box below' : outcomeOf(request)}</p>
        </div>
    );
}

/** What a turn changed, t3code's card under the reply: "Changed 3 files +7 −2", each file a row, Open diff. */
export function ChangesCard({ files, onOpen }: { files: AgentStepDiff[]; onOpen?: () => void }) {
    const total = diffStat(files);
    return (
        <div data-testid="changed-files" className="mt-3 overflow-hidden rounded-[26px] bg-foreground/[0.03] ring-1 ring-inset ring-foreground/[0.05]">
            <div className="flex items-center gap-2 py-1.5 pl-4 pr-1.5">
                <span className="text-xs font-medium">
                    Changed {files.length} {files.length === 1 ? 'file' : 'files'}
                </span>
                <DiffStat {...total} className="text-[11px]" />
                {onOpen && (
                    <button type="button" onClick={onOpen} className={cn(XS_BUTTON, XS_GHOST, 'ml-auto h-6 px-2')}>
                        <FileDiff className="h-3 w-3" strokeWidth={2} />
                        Open diff
                    </button>
                )}
            </div>
            <ul className="px-1.5 pb-1.5">
                {files.map((f) => {
                    const stat = diffStat([f]);
                    return (
                        <li key={f.path}>
                            <button type="button" onClick={onOpen} disabled={!onOpen} className="flex h-7 w-full items-center gap-2 rounded-full px-2.5 text-left transition-colors enabled:hover:bg-foreground/[0.04]">
                                <span className="min-w-0 truncate font-mono text-xs text-foreground/85">
                                    {f.path.includes('/') && <span className="text-muted-foreground">{f.path.slice(0, f.path.lastIndexOf('/') + 1)}</span>}
                                    {f.path.slice(f.path.lastIndexOf('/') + 1)}
                                </span>
                                <DiffStat {...stat} className="ml-auto shrink-0 text-[10px]" />
                            </button>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

/** Where the conversation starts: who the agent is and what it runs on. */
export function ConversationIntro({ face, name, line, children }: { face: ReactNode; name: string; line: string; children?: ReactNode }) {
    return (
        <div className="px-1 pb-2 pt-10">
            {face}
            <h2 className="mt-4 font-brand text-[24px] font-semibold tracking-[-0.02em] [overflow-wrap:anywhere]">{name}</h2>
            <p className="mt-1 text-sm text-muted-foreground [overflow-wrap:anywhere]">{line}</p>
            {children}
        </div>
    );
}
