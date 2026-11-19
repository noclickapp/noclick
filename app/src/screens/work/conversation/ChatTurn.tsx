// A turn a chat app's message started (a WhatsApp message now; any chat app's trigger draws the same), as it looked in
// that chat: what came in as the other side's bubble (its writer in a group, a voice note with its transcript, a picture
// or a file, what it quoted, its time) with reactions under it, the agent's replies as its own bubbles with their time
// and a sent tick, and what it decided as small notes between them: it stayed quiet and why, a reminder, a note,
// something it looked up, a call that failed, one held for your yes (Approve or Decline, the request's own answer).
// While it works, its typing and its live steps; done, "Handled by <agent> · 4s" with the steps a tap away. The chat's
// name and picture head the first of a run of its turns. Built on NoClick's own fills: a sent bubble is a green wash
// over the popover, never the chat app's own colours.
import { useState, type ReactNode } from 'react';
import { CheckCheck, ChevronRight, Contact, FileText, Film, Image as ImageIcon, MapPin, Paperclip, Pause, Play } from 'lucide-react';
import type { HarnessRequest, RequestDecision } from 'noclick';
import { useHumanRequest } from '@/screens/humans/useHumanRequest';
import { formatPhoneForDisplay } from '@/lib/phoneFormat';
import { NodeMark } from '@/ui/primitives';
import { MemberAvatar } from '@/screens/channels/avatars';
import type { ChannelMember } from '@/screens/channels/types';
import { cn } from '@/ui/utils';
import { stepsOf, type Failure, type Step, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import type { ActivityChat, ActivityMedia, Did, Inbound, TurnActivity } from '@/lib/agentThread/turnActivity';
import { useWorkClient } from '../client';
import { Elapsed, failedStep, Shine, StepList, toolWords, type ToolCalls } from './Activity';
import { ApprovalRow, PlanCard, QuestionSummary, RefusedNote } from './Rows';
import { clockOf, spent, XS_BUTTON, XS_OUTLINE, XS_PRIMARY } from './styles';
import { ownerOnlyWhy, useOwnerOnly } from '@/screens/console/ownerOnly';

/** The agent the chat's other side is talking to. */
export interface ChatAgent {
    name: string;
    face: ChannelMember;
}

export interface ChatTurnProps {
    /** What came in and what it did; null while its read is on the way (a turn just heard). */
    activity: TurnActivity | null;
    /** The chat it happened in. */
    chat: ActivityChat;
    /** The message its trigger started it with, as the thread keeps it. */
    entry: UserEntry;
    /** Its turn in the thread: its live steps while it works, its kept steps once done. */
    turn: TurnEntry | null;
    agent: ChatAgent;
    /** Name the chat above it (the first of a run of its turns). */
    header: boolean;
    mode: ToolCalls;
    requests: HarnessRequest[];
    onAnswer: (request: HarnessRequest, decision: RequestDecision) => void;
    onReconnect?: (failure: Failure) => void;
    /** A line beside it already says why it failed (a model switch's). */
    failureTold?: boolean;
    /** The cards its calls of NoClick's own tools draw, under its footer. */
    cards?: ReactNode;
}

/** A sent bubble's fill: a green wash over the popover, as a sent message reads in a chat. */
const SENT = 'bg-[color-mix(in_srgb,theme(colors.green.700)_13%,hsl(var(--popover)))] dark:bg-[color-mix(in_srgb,theme(colors.green.400)_13%,hsl(var(--popover)))]';
const PILL = 'max-w-[92%] self-center rounded-full bg-popover px-3 py-[3px] text-center text-xs leading-5 text-muted-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.08] [overflow-wrap:anywhere]';
const KIND_WORDS: Record<string, string> = { direct: 'Direct chat', group: 'Group', self: 'Your own chat' };

/** Who a chat is with, in a name: a person's, a group's, else their number; your own chat says so. */
export function chatName(chat: ActivityChat): string {
    if (chat.kind === 'self') return 'Message yourself';
    return chat.name ?? (chat.number ? formatPhoneForDisplay(chat.number) : chat.kind === 'group' ? 'A group' : chat.key);
}

const initialsOf = (name: string) =>
    name
        .split(/\s+/)
        .filter((w) => /[\p{L}\p{N}]/u.test(w))
        .slice(0, 2)
        .map((w) => Array.from(w)[0]!.toUpperCase())
        .join('') || '?';

/** A person's or a group's picture on the chat app, else their initials. */
export function PersonDisc({ name, avatar, size = 28, className }: { name: string; avatar: string | null; size?: 20 | 28 | 32; className?: string }) {
    const [broken, setBroken] = useState(false);
    const box = size === 20 ? 'h-5 w-5 text-[9px]' : size === 28 ? 'h-7 w-7 text-[11px]' : 'h-8 w-8 text-[12px]';
    if (avatar && !broken) return <img src={avatar} alt="" aria-hidden onError={() => setBroken(true)} className={cn('shrink-0 rounded-full bg-foreground/[0.08] object-cover', box, className)} data-avatar />;
    return (
        <span aria-hidden className={cn('inline-flex shrink-0 select-none items-center justify-center rounded-full bg-foreground/[0.1] font-semibold leading-none text-foreground/80', box, className)} data-initials>
            {initialsOf(name)}
        </span>
    );
}

function ChatHeader({ chat }: { chat: ActivityChat }) {
    const name = chatName(chat);
    const where = KIND_WORDS[chat.kind ?? 'direct'];
    // Your own chat wears your own picture, else your initials.
    const face = chat.kind === 'self' ? (chat.name ?? 'You') : name;
    const number = chat.kind === 'direct' && chat.name && chat.number ? formatPhoneForDisplay(chat.number) : null;
    return (
        <div className="flex items-center gap-2.5 border-b border-border px-3.5 py-2.5 dark:border-foreground/[0.08]" data-chat-header>
            <PersonDisc name={face} avatar={chat.avatar} size={32} />
            <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold leading-5">{name}</p>
                <p className="flex min-w-0 items-center gap-1 text-xs leading-4 text-muted-foreground">
                    {chat.nodeType && <NodeMark type={chat.nodeType} size="xs" />}
                    <span className="truncate">
                        {where}
                        {number && ` · ${number}`}
                    </span>
                </p>
            </div>
        </div>
    );
}

const minutes = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

/** A voice note: play it where its file was kept, its length, and what it said. */
function VoiceNote({ media, running }: { media: ActivityMedia; running: boolean }) {
    const [audio, setAudio] = useState<HTMLAudioElement | null>(null);
    const [playing, setPlaying] = useState(false);
    const toggle = () => {
        if (!media.url) return;
        const a = audio ?? new Audio(media.url);
        if (!audio) {
            a.onended = () => setPlaying(false);
            a.onpause = () => setPlaying(false);
            a.onplay = () => setPlaying(true);
            setAudio(a);
        }
        if (a.paused) void a.play().catch((e: unknown) => console.warn('[work] the voice note didn’t play:', e));
        else a.pause();
    };
    return (
        <div data-voice>
            <div className="flex items-center gap-2.5">
                <button
                    type="button"
                    onClick={toggle}
                    disabled={!media.url}
                    aria-label={playing ? 'Pause the voice note' : 'Play the voice note'}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-foreground text-background transition-transform active:scale-95 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
                >
                    {playing ? <Pause className="h-3 w-3 fill-current" strokeWidth={0} /> : <Play className="ml-0.5 h-3 w-3 fill-current" strokeWidth={0} />}
                </button>
                <span aria-hidden className="h-[22px] min-w-[80px] flex-1 bg-[repeating-linear-gradient(90deg,hsl(var(--muted-foreground))_0_2px,transparent_2px_5px)] opacity-55 [clip-path:polygon(0_40%,8%_20%,16%_55%,24%_10%,32%_45%,40%_25%,48%_60%,56%_15%,64%_50%,72%_30%,80%_55%,88%_20%,100%_45%,100%_100%,0_100%)]" />
                {media.duration !== null && <span className="text-xs tabular-nums text-muted-foreground">{minutes(media.duration)}</span>}
            </div>
            {media.transcript ? (
                <div className="mt-1.5">
                    <span className="block text-xs text-muted-foreground">Transcript</span>
                    <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{media.transcript}</p>
                </div>
            ) : (
                running && <p className="mt-1.5 text-xs text-muted-foreground">Listening to it…</p>
            )}
        </div>
    );
}

const FILE_WORDS: Record<string, { label: string; icon: typeof FileText }> = {
    image: { label: 'Photo', icon: ImageIcon },
    video: { label: 'Video', icon: Film },
    document: { label: 'Document', icon: FileText },
    file: { label: 'File', icon: Paperclip },
    location: { label: 'Location', icon: MapPin },
    contact: { label: 'Contact card', icon: Contact },
    audio: { label: 'Audio', icon: Paperclip },
};

/** A file a message carried: a picture as itself where its copy was kept, anything else as a chip that opens it. */
function SentFile({ media }: { media: { kind: string; url: string | null } }) {
    if (media.kind === 'image' && media.url)
        return (
            <a href={media.url} target="_blank" rel="noopener noreferrer" className="mb-1 block">
                <img src={media.url} alt="What they sent" className="max-h-60 max-w-full rounded-xl object-cover" />
            </a>
        );
    const { label, icon: Icon } = FILE_WORDS[media.kind] ?? FILE_WORDS.file;
    const chip = (
        <span className="mb-1 inline-flex h-8 items-center gap-1.5 rounded-full bg-foreground/[0.06] px-3 text-xs text-foreground/85">
            <Icon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
            {label}
        </span>
    );
    return media.url ? (
        <a href={media.url} target="_blank" rel="noopener noreferrer" className="block w-fit">
            {chip}
        </a>
    ) : (
        <span className="block w-fit">{chip}</span>
    );
}

function Time({ at, children }: { at: number | null; children?: ReactNode }) {
    return (
        <span className="float-right ml-2 mt-1.5 flex items-center gap-1 text-[11px] leading-4 text-muted-foreground">
            {at !== null && (
                <time dateTime={new Date(at).toISOString()} className="tabular-nums">
                    {clockOf(at)}
                </time>
            )}
            {children}
        </span>
    );
}

const writerOf = (m: Inbound) => m.senderName ?? (m.senderNumber ? formatPhoneForDisplay(m.senderNumber) : 'Someone');
const sameWriter = (a: Inbound, b: Inbound) => (a.senderId ?? a.senderName) === (b.senderId ?? b.senderName);

/** One message that came in: its writer in a group (on the first of their run), what it quoted, a voice note with its
 *  transcript or a file, its words and time. */
function Bubble({ message, named, first, running }: { message: Inbound; named: boolean; first: boolean; running: boolean }) {
    const voice = message.media && (message.media.kind === 'voice' || message.media.kind === 'audio') ? message.media : null;
    return (
        <div className={cn('max-w-full rounded-2xl rounded-bl-md bg-popover px-3 py-[7px] text-sm leading-relaxed text-foreground shadow-[0_1px_0_hsl(var(--foreground)/0.08)]', !first && 'rounded-tl-md')} data-incoming>
            {named && <span className="block text-xs font-semibold leading-5 text-muted-foreground">{writerOf(message)}</span>}
            {message.quotedText && <div className="mb-1.5 border-l-2 border-foreground/25 py-0.5 pl-2.5 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{message.quotedText}</div>}
            {voice ? <VoiceNote media={voice} running={running} /> : message.media && <SentFile media={message.media} />}
            {message.text && <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">{message.text}</span>}
            <Time at={message.at} />
        </div>
    );
}

/** What came in, oldest first, as the chat showed it: a writer's messages in a row together (in a group, their name on
 *  the first and their picture beside the last), each with the reactions under it. */
function IncomingRuns({ messages, group, running, reactionsOn }: { messages: Inbound[]; group: boolean; running: boolean; reactionsOn: (message: Inbound) => Did[] }) {
    const runs: Inbound[][] = [];
    for (const m of messages) {
        const run = runs[runs.length - 1];
        if (run && sameWriter(run[0], m)) run.push(m);
        else runs.push([m]);
    }
    return (
        <>
            {runs.map((run, r) => (
                <div key={r} className="flex max-w-[86%] items-end gap-1.5 self-start" data-incoming-run>
                    {group && <PersonDisc name={writerOf(run[0])} avatar={run.find((m) => m.senderAvatar)?.senderAvatar ?? null} size={28} />}
                    <div className="flex min-w-0 flex-col items-start gap-0.5">
                        {run.map((m, i) => (
                            <div key={m.messageId ?? i} className="flex max-w-full flex-col">
                                <Bubble message={m} named={group && i === 0} first={i === 0} running={running} />
                                <Reactions reactions={reactionsOn(m)} />
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </>
    );
}

function Reactions({ reactions, end }: { reactions: Did[]; end?: boolean }) {
    if (!reactions.length) return null;
    return (
        <span className={cn('relative -mt-2 flex w-fit gap-0.5 rounded-full bg-popover px-1.5 text-[13px] leading-5 ring-1 ring-inset ring-border dark:ring-foreground/[0.1]', end ? 'mr-2.5 self-end' : 'ml-2.5 self-start')} data-reaction>
            {reactions.map((r, i) => (
                <span key={i}>{r.emoji ?? '👍'}</span>
            ))}
        </span>
    );
}

function Outgoing({ did }: { did: Did }) {
    return (
        <div className={cn('max-w-[82%] self-end rounded-2xl rounded-br-md px-3 py-[7px] text-sm leading-relaxed text-foreground', SENT)} data-outgoing>
            {did.media && <SentFile media={did.media} />}
            {did.text && <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">{did.text}</span>}
            <Time at={did.at}>
                {did.edited && <span>Edited</span>}
                <CheckCheck aria-label="Sent" className="h-3.5 w-3.5 text-green-600 dark:text-green-400" strokeWidth={2.25} />
            </Time>
        </div>
    );
}

/** A wake-up's time as a person reads it: an exact one "for Sun 11:00 AM", else as it was set ("in 30 minutes"). */
function whenWords(when: string): string {
    const at = Date.parse(when);
    if (!/\d{4}-\d{2}-\d{2}/.test(when) || Number.isNaN(at)) return when;
    return `for ${new Date(at).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' })}`;
}

/** What a step it took said, in a pill. */
function pillWords(d: Did, agent: string): string {
    const text = d.text?.trim() ?? '';
    switch (d.kind) {
        case 'quiet':
            return text ? `${agent} stayed quiet: ${text}` : `${agent} stayed quiet`;
        case 'reminder':
            return `Set a reminder${d.when ? ` ${whenWords(d.when)}` : ''}${text ? `: ${text}` : ''}`;
        case 'note':
            if (d.tool === 'human__notify') return `Told you: “${text}”`;
            if (d.tool === 'human__ask') return `Asked you: “${text}”`;
            if (d.tool === 'memory__save') return `Saved ${d.name ?? 'a note'} to its memory`;
            return 'Saved a note about this chat';
        case 'found':
            return text ? `Looked up “${text}”` : 'Looked something up';
        case 'failed': {
            if (!d.tool) return text ? `It didn’t finish: ${text}` : 'It didn’t finish';
            const why = text.startsWith(`${d.tool}: `) ? text.slice(d.tool.length + 2) : text;
            return `${toolWords(d.tool)} didn’t go through${why ? `: ${why}` : ''}`;
        }
        default:
            return text;
    }
}

/** A call held for your yes, answered here as on the request's own page. */
function HeldPill({ did }: { did: Did }) {
    const what = did.text ? did.text.charAt(0).toUpperCase() + did.text.slice(1) : 'A call';
    if (!did.heldRequestId) return <span className={cn(PILL, 'text-foreground')}>Waiting for your yes: {what}</span>;
    return <HeldRequest requestId={did.heldRequestId} what={what} />;
}

function HeldRequest({ requestId, what }: { requestId: string; what: string }) {
    const { question, answering, failure, answer } = useHumanRequest(useWorkClient(), requestId);
    // A call held for a yes is the account's owner's to answer (screens/console/ownerOnly.ts).
    const answers = useOwnerOnly()('heldCalls');
    const status = question?.status;
    if (status === 'answered') return <span className={PILL}>{question?.answer?.approved === false ? `You declined, so it didn’t run: ${what}` : `Approved: ${what}`}</span>;
    if (status === 'expired') return <span className={PILL}>Nobody approved it in time, so it didn’t run: {what}</span>;
    if (status === 'canceled') return <span className={PILL}>Withdrawn, so it didn’t run: {what}</span>;
    return (
        <div className="flex max-w-[92%] flex-col items-center gap-2 self-center rounded-2xl bg-popover px-3.5 py-2.5 text-center text-xs leading-5 text-foreground ring-1 ring-inset ring-foreground/25 [overflow-wrap:anywhere]" data-held>
            <span>Waiting for your yes: {what}</span>
            {!answers && <span className="text-muted-foreground">{ownerOnlyWhy('heldCalls')}</span>}
            <span className={cn('flex flex-wrap justify-center gap-1.5', !answers && 'hidden')}>
                <button type="button" disabled={answering || !question} onClick={() => void answer({ approved: true, note: null })} className={cn(XS_BUTTON, XS_PRIMARY, 'px-3.5')}>
                    Approve
                </button>
                <button type="button" disabled={answering || !question} onClick={() => void answer({ approved: false, note: null })} className={cn(XS_BUTTON, XS_OUTLINE, 'px-3.5')}>
                    Decline
                </button>
            </span>
            {failure && <span className="text-red-600 dark:text-red-400">{failure}</span>}
        </div>
    );
}

/** Its reply on the way: three dots on its side of the chat. */
function Typing({ name }: { name: string }) {
    return (
        <div className={cn('self-end rounded-2xl rounded-br-md px-3.5 py-3', SENT)} data-typing role="status" aria-label={`${name} is typing`}>
            <span className="wc-typing flex items-center gap-1" aria-hidden>
                <span className="h-1.5 w-1.5 rounded-full bg-foreground/50" />
                <span className="h-1.5 w-1.5 rounded-full bg-foreground/50" />
                <span className="h-1.5 w-1.5 rounded-full bg-foreground/50" />
            </span>
        </div>
    );
}

/** What came in, before its read lands: a bubble's outline. */
function IncomingSoon() {
    return (
        <div aria-label="A message came in" className="w-48 max-w-[82%] space-y-1.5 self-start rounded-2xl rounded-bl-md bg-popover px-3 py-2.5 shadow-[0_1px_0_hsl(var(--foreground)/0.08)]" data-incoming-soon>
            <div className="h-2 w-4/5 animate-pulse rounded-full bg-foreground/[0.08] motion-reduce:animate-none" />
            <div className="h-2 w-1/2 animate-pulse rounded-full bg-foreground/[0.08] motion-reduce:animate-none" />
        </div>
    );
}

/** Its calls as steps, where its turn kept none of its own (the record's). */
const recordedSteps = (a: TurnActivity): Step[] =>
    a.turn.steps.map((s, i) => ({
        id: `${a.turn.id}:${i}`,
        kind: 'tool',
        tool: s.tool,
        source: null,
        command: null,
        path: null,
        query: null,
        arguments: {},
        output: '',
        exitCode: null,
        durationMs: null,
        isError: !!s.error,
        result: s.error,
        diffs: [],
        running: false,
        at: s.at,
        parent: null,
        children: [],
        said: '',
        saidId: null,
        saidAt: null,
    }));

/** "Handled by WhatsApp · 4s ›", its steps opening under it (while it works, its live steps, open), and the cards its
 *  calls of NoClick's own tools draw. */
function Footer({ agent, running, failed, from, worked, steps, mode, cards }: { agent: ChatAgent; running: boolean; failed: boolean; from: number; worked: number | null; steps: Step[]; mode: ToolCalls; cards?: ReactNode }) {
    const [open, setOpen] = useState(false);
    const shown = mode === 'all' ? steps : mode === 'failures' ? steps.filter((s) => s.running || failedStep(s)) : [];
    const expanded = running || open;
    const opens = !running && shown.length > 0;
    const label = running ? null : failed ? `${agent.name} didn’t finish` : `Handled by ${agent.name}`;
    return (
        <div className="border-t border-border px-3.5 py-2 text-[12.5px] leading-5 text-muted-foreground dark:border-foreground/[0.08]" data-chat-footer>
            <div className="flex min-h-6 items-center gap-2">
                <MemberAvatar member={agent.face} size={20} state={running ? 'working' : failed ? 'failed' : undefined} />
                {running ? (
                    <span className="min-w-0 truncate" aria-live="polite">
                        <Shine>{agent.name} is working</Shine> · <Elapsed from={from} />
                    </span>
                ) : (
                    <button
                        type="button"
                        onClick={() => opens && setOpen(!open)}
                        aria-expanded={opens ? open : undefined}
                        disabled={!opens}
                        className="flex min-w-0 items-center gap-1 rounded-full text-left transition-colors enabled:hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:cursor-default"
                    >
                        <span className="truncate">{label}</span>
                        {worked !== null && <span className="shrink-0 tabular-nums">· {spent(worked)}</span>}
                        {opens && <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 transition-transform duration-200', open && 'rotate-90')} strokeWidth={2} />}
                    </button>
                )}
            </div>
            <div className={cn('grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none', expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                <div className="min-h-0 overflow-hidden" inert={!expanded || undefined}>
                    {shown.length > 0 && <StepList steps={shown} live={running} className="mt-1 border-l border-border pl-2 dark:border-foreground/[0.1]" />}
                </div>
            </div>
            {cards}
        </div>
    );
}

export function ChatTurn({ activity, chat, entry, turn, agent, header, mode, requests, onAnswer, onReconnect, failureTold, cards }: ChatTurnProps) {
    // At work until both its thread and its record say it's done, so the reply its record brings lands in place of
    // the typing rather than after the footer already settled.
    const running = !activity || activity.turn.status === 'running' || turn?.status === 'running';
    const failed = !running && (activity?.turn.status === 'failed' || turn?.status === 'failed');
    const did = activity?.did ?? [];
    const group = chat.kind === 'group';
    // A reaction sits under the message it reacts to: one of its replies, one that came in, else the last that did.
    const replyIds = new Set(did.flatMap((d) => (d.kind === 'reply' && d.messageId ? [d.messageId] : [])));
    const onReply = (d: Did) => d.kind === 'reaction' && !!d.messageId && replyIds.has(d.messageId);
    const inbound = activity?.inbound ?? [];
    const inboundIds = new Set(inbound.flatMap((m) => (m.messageId ? [m.messageId] : [])));
    const last = inbound[inbound.length - 1];
    const reactionsOn = (m: Inbound) => did.filter((d) => d.kind === 'reaction' && !onReply(d) && (d.messageId && inboundIds.has(d.messageId) ? d.messageId === m.messageId : m === last));
    // A failed turn whose provider refused its key says so with what to do, rather than as a pill.
    const told = did.filter((d) => !(d.kind === 'failed' && !d.tool && turn?.failure));
    const from = activity?.turn.startedAt ?? turn?.startedAt ?? entry.at;
    const worked = activity?.turn.workedS != null ? activity.turn.workedS * 1000 : turn?.endedAt ? turn.endedAt - turn.startedAt : null;
    const steps = turn && stepsOf(turn).length ? stepsOf(turn) : activity ? recordedSteps(activity) : [];
    return (
        <div className="group/chat pt-3" data-row="chat-turn" data-status={running ? 'running' : failed ? 'failed' : 'done'} data-turn={activity?.turn.id ?? entry.operationId ?? undefined}>
            <div className="overflow-hidden rounded-[22px] ring-1 ring-inset ring-border dark:ring-foreground/[0.08]">
                {header && <ChatHeader chat={chat} />}
                <div className="flex flex-col gap-2 bg-foreground/[0.04] px-3.5 py-3.5">
                    {inbound.length ? <IncomingRuns messages={inbound} group={group} running={running} reactionsOn={reactionsOn} /> : <IncomingSoon />}
                    {told.map((d, i) =>
                        d.kind === 'reaction' ? null : d.kind === 'reply' ? (
                            <div key={i} className="flex flex-col">
                                <Outgoing did={d} />
                                <Reactions reactions={did.filter((r) => onReply(r) && r.messageId === d.messageId)} end />
                            </div>
                        ) : d.kind === 'held' ? (
                            <HeldPill key={i} did={d} />
                        ) : (
                            <span key={i} className={cn(PILL, d.kind === 'failed' && 'text-red-600 dark:text-red-400', d.kind === 'quiet' && 'line-clamp-3')} data-pill={d.kind}>
                                {pillWords(d, agent.name)}
                            </span>
                        )
                    )}
                    {running && <Typing name={agent.name} />}
                </div>
                {turn?.failure && <RefusedNote failure={turn.failure} told={failureTold} onReconnect={onReconnect} className="border-t border-border px-3.5 pb-3 dark:border-foreground/[0.08]" />}
                {requests.length > 0 && (
                    <div className="border-t border-border px-3.5 pb-2.5 dark:border-foreground/[0.08]">
                        {requests.map((r) => (r.kind === 'question' ? <QuestionSummary key={r.id} request={r} /> : r.action === 'plan' ? <PlanCard key={r.id} request={r} onAnswer={onAnswer} /> : <ApprovalRow key={r.id} request={r} onAnswer={onAnswer} />))}
                    </div>
                )}
                <Footer agent={agent} running={running} failed={failed} from={from} worked={worked} steps={steps} mode={mode} cards={cards} />
            </div>
        </div>
    );
}
