// A turn a channel's posts started, as it looked in the channel: the channel (and the thread its reply posts in) at its
// head, the posts it was handed with who wrote them and when, then the agent's own row. While it works that row says
// what it's doing now in a few words ("Reading worker.py · 12s") and its reply arrives there as it writes it; done, its
// reply with its time, or that it stayed quiet. Its steps wait behind one line in the foot ("Working for 12s · 3 steps",
// then "Handled by Wirefern · 14s · 3 steps"), and the text the agent read (ids and the rules for replying) is a fold
// under the card: what you read is what was said in the channel, never the prompt built from it.
import { useState, type ReactNode } from 'react';
import { ChevronRight, Eye, Hash, MessagesSquare, SquareArrowOutUpRight } from 'lucide-react';
import type { ChannelAuthor, HarnessRequest, MessageChannel, MessageChannelPost, RequestDecision } from 'noclick';
import { MemberAvatar } from '@/screens/channels/avatars';
import { MessageBody } from '@/screens/channels/MessageBody';
import { authorMember, YOU } from '@/screens/channels/model';
import type { ChannelAuthor as PostAuthor, ChannelMember } from '@/screens/channels/types';
import { cn } from '@/ui/utils';
import { allStepsOf, stepsOf, type Failure, type Step, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import { doing, Elapsed, failedStep, Shine, StepList, type ToolCalls } from './Activity';
import { ApprovalRow, PlanCard, QuestionSummary, RefusedNote } from './Rows';
import { clockOf, spent } from './styles';

export interface ChannelTurnProps {
    entry: UserEntry & { channel: MessageChannel };
    /** Its turn, once the thread has it. */
    turn: TurnEntry | null;
    agent: { name: string; face: ChannelMember };
    /** Whether a post's author is you, as the page reads its people. */
    mine: (author: ChannelAuthor) => boolean;
    /** The channel's name and kind over its posts: the first of a run of its turns. */
    header: boolean;
    mode: ToolCalls;
    requests: HarnessRequest[];
    onAnswer: (request: HarnessRequest, decision: RequestDecision) => void;
    onReconnect?: (failure: Failure) => void;
    failureTold?: boolean;
    /** Opens the channel (at the thread its reply posts in). */
    onOpen?: (channelId: string, thread?: string) => void;
    /** The cards its calls of NoClick's own tools draw, under its foot. */
    cards?: ReactNode;
}

const NO_CHANNELS = new Map<string, string>();

/** A post's author as the channel draws them: you, an agent, a person. */
function memberOf(author: ChannelAuthor, mine: ChannelTurnProps['mine']): ChannelMember {
    if (mine(author)) return YOU;
    // The account's own post, read by someone else (a person in its space): its owner's.
    if (author.type === 'account' && !author.id) return { id: 'account', kind: 'human', name: 'The owner' };
    return authorMember({ ...author, type: author.type as PostAuthor['type'], name: author.name ?? '' }, []) ?? { id: `${author.type}:${author.id ?? author.name}`, kind: 'human', name: author.name || 'Someone' };
}

/** What it's doing now, in a few words: the step running, else how far it's got. */
export function nowWords(turn: TurnEntry): string {
    if (turn.downloading) return turn.downloading.text;
    if (turn.compacting) return 'Compacting its context';
    const running = allStepsOf(turn).filter((s) => s.running);
    if (running.length) return doing(running[running.length - 1]!);
    if (turn.reasoning.length) return 'Thinking';
    return stepsOf(turn).length ? 'Working' : 'Starting';
}

/** Its reply so far: whole once it's in, else what it has written. */
const replyOf = (turn: TurnEntry | null): string => (turn ? (turn.reply ?? turn.parts.flatMap((p) => (p.kind === 'text' ? [p.text] : [])).join('\n\n')).trim() : '');

function Row({ member, name, at, agent, children }: { member: ChannelMember; name: string; at: number | null; agent?: boolean; children: ReactNode }) {
    return (
        <div className="flex gap-2.5" data-post>
            <MemberAvatar member={member} size={28} className="mt-0.5" />
            <div className="min-w-0 flex-1">
                <p className="flex min-w-0 items-baseline gap-1.5 text-[13px] leading-5">
                    <span className="truncate font-semibold text-foreground">{name}</span>
                    {agent && <span className="shrink-0 rounded px-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.12]">Agent</span>}
                    {at !== null && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{clockOf(at)}</span>}
                </p>
                <div className="text-[14px] leading-relaxed text-foreground/90">{children}</div>
            </div>
        </div>
    );
}

function Post({ post, mine, members }: { post: MessageChannelPost; mine: ChannelTurnProps['mine']; members: ChannelMember[] }) {
    const member = memberOf(post.author, mine);
    return (
        <Row member={member} name={member.name} at={post.createdAt?.getTime() ?? null} agent={member.kind === 'agent'}>
            {post.text && <MessageBody text={post.text} members={members} channels={NO_CHANNELS} onChannel={() => {}} />}
            {post.files.length > 0 && <p className="text-xs text-muted-foreground">{post.files.map((f) => f.name).join(', ')}</p>}
        </Row>
    );
}

/** "Working for 12s · 3 steps" while it works, "Handled by Wirefern · 14s · 3 steps" once it's done, opening to them. */
function Foot({ agentName, turn, running, failed, from, mode }: { agentName: string; turn: TurnEntry; running: boolean; failed: boolean; from: number; mode: ToolCalls }) {
    const [open, setOpen] = useState(false);
    const steps: Step[] = stepsOf(turn);
    const shown = mode === 'all' ? steps : mode === 'failures' ? steps.filter((s) => s.running || failedStep(s)) : [];
    const n = steps.length;
    const count = n ? ` · ${n} ${n === 1 ? 'step' : 'steps'}` : '';
    const opens = shown.length > 0 || (running && turn.reasoning.length > 0);
    const worked = turn.endedAt ? turn.endedAt - turn.startedAt : null;
    return (
        <div className="border-t border-border px-3.5 py-2 text-[12.5px] leading-5 text-muted-foreground dark:border-foreground/[0.08]" data-channel-foot>
            <button
                type="button"
                onClick={() => opens && setOpen(!open)}
                aria-expanded={opens ? open : undefined}
                disabled={!opens}
                className="flex min-h-6 min-w-0 items-center gap-1 rounded-full text-left transition-colors enabled:hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:cursor-default"
            >
                {running ? (
                    <span className="truncate">
                        Working for <Elapsed from={from} />
                        {count}
                    </span>
                ) : (
                    <span className="truncate">
                        {failed ? `${agentName} didn’t finish` : `Handled by ${agentName}`}
                        {worked !== null && ` · ${spent(worked)}`}
                        {count}
                    </span>
                )}
                {opens && <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 transition-transform duration-200', open && 'rotate-90')} strokeWidth={2} />}
            </button>
            <div className={cn('grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none', open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                <div className="min-h-0 overflow-hidden" inert={!open || undefined}>
                    {running && turn.reasoning.length > 0 && <p className="mt-1 line-clamp-3 italic text-muted-foreground/80">{turn.reasoning[turn.reasoning.length - 1]}</p>}
                    {shown.length > 0 && <StepList steps={shown} live={running} className="mt-1 border-l border-border pl-2 dark:border-foreground/[0.1]" />}
                </div>
            </div>
        </div>
    );
}

/** The text the agent was handed, behind one line under the card. */
function ReadFold({ name, text }: { name: string; text: string }) {
    const [open, setOpen] = useState(false);
    return (
        <div className="mt-1.5 px-1" data-channel-read>
            <button
                type="button"
                onClick={() => setOpen(!open)}
                aria-expanded={open}
                className="flex min-h-6 items-center gap-1.5 rounded-full text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
            >
                <Eye className="h-3.5 w-3.5" strokeWidth={2} />
                What {name} read
                <ChevronRight className={cn('h-3.5 w-3.5 transition-transform duration-200', open && 'rotate-90')} strokeWidth={2} />
            </button>
            {open && <pre className="mt-1.5 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-foreground/[0.04] px-3 py-2.5 font-mono text-[12px] leading-relaxed text-muted-foreground">{text}</pre>}
        </div>
    );
}

export function ChannelTurn({ entry, turn, agent, mine, header, mode, requests, onAnswer, onReconnect, failureTold, onOpen, cards }: ChannelTurnProps) {
    const { channel } = entry;
    // No turn: it ended having drawn nothing (its turn begins as its message shows, history keeps none that drew nothing).
    const running = turn?.status === 'running';
    const failed = turn?.status === 'failed';
    const reply = replyOf(turn);
    const from = turn?.startedAt ?? entry.at;
    // Everyone the card names, so an @mention of one of them reads as the channel draws it.
    const members = [agent.face, ...channel.posts.map((p) => memberOf(p.author, mine))];
    const where = channel.thread ? `A thread in #${channel.name}` : (channel.space?.name ?? 'Channel');
    const started = !!turn && (turn.parts.length > 0 || turn.reasoning.length > 0);
    let own: ReactNode;
    if (!running && !reply) own = <p className="text-muted-foreground">{failed ? 'Didn’t finish.' : 'Stayed quiet.'}</p>;
    else if (reply)
        own = (
            <div className={cn(running && "[&_p:last-of-type]:after:ml-0.5 [&_p:last-of-type]:after:inline-block [&_p:last-of-type]:after:h-[1em] [&_p:last-of-type]:after:w-[2px] [&_p:last-of-type]:after:animate-pulse [&_p:last-of-type]:after:bg-foreground/70 [&_p:last-of-type]:after:align-[-0.15em] [&_p:last-of-type]:after:content-['']")} data-writing={running || undefined}>
                <MessageBody text={reply} members={members} channels={NO_CHANNELS} onChannel={() => {}} />
            </div>
        );
    else
        own = (
            <p className="flex min-w-0 items-baseline gap-1.5 text-muted-foreground" aria-live="polite" data-channel-now>
                <Shine className="truncate">{turn ? nowWords(turn) : 'Starting'}</Shine>
                <span className="shrink-0 text-xs">
                    <Elapsed from={from} />
                </span>
            </p>
        );
    return (
        <div className="pt-3" data-row="channel-turn" data-status={running ? 'running' : failed ? 'failed' : 'done'} data-turn={entry.operationId ?? undefined}>
            <div className="overflow-hidden rounded-[22px] ring-1 ring-inset ring-border dark:ring-foreground/[0.08]">
                {header && (
                    <div className="flex items-center gap-2.5 border-b border-border px-3.5 py-2.5 dark:border-foreground/[0.08]" data-channel-header>
                        <span aria-hidden className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-foreground/[0.06] text-foreground/80">
                            <Hash className="h-4 w-4" strokeWidth={2} />
                        </span>
                        <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold leading-5">{channel.name}</p>
                            <p className="truncate text-xs leading-4 text-muted-foreground">{where}</p>
                        </div>
                        {onOpen && (
                            <button
                                type="button"
                                onClick={() => onOpen(channel.id, channel.thread?.id)}
                                className="inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-xs text-foreground/85 ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 max-md:h-10 dark:ring-foreground/[0.12]"
                            >
                                Open
                                <SquareArrowOutUpRight className="h-3 w-3" strokeWidth={2} />
                            </button>
                        )}
                    </div>
                )}
                <div className="flex flex-col gap-3 bg-foreground/[0.03] px-3.5 py-3.5">
                    {channel.thread && (
                        <p className="flex min-w-0 items-start gap-1.5 text-xs leading-5 text-muted-foreground" data-channel-thread>
                            <MessagesSquare className="mt-[3px] h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                            <span className="min-w-0">
                                Thread on <b className="font-semibold text-foreground/80">{memberOf(channel.thread.author, mine).name}</b>’s message: “{channel.thread.text}”
                            </span>
                        </p>
                    )}
                    {channel.posts.map((p) => (
                        <Post key={p.id} post={p} mine={mine} members={members} />
                    ))}
                    <Row member={agent.face} name={agent.name} at={!running && reply && turn?.endedAt ? turn.endedAt : null} agent>
                        {own}
                    </Row>
                </div>
                {turn?.failure && <RefusedNote failure={turn.failure} told={failureTold} onReconnect={onReconnect} className="border-t border-border px-3.5 pb-3 dark:border-foreground/[0.08]" />}
                {requests.length > 0 && (
                    <div className="border-t border-border px-3.5 pb-2.5 dark:border-foreground/[0.08]">
                        {requests.map((r) => (r.kind === 'question' ? <QuestionSummary key={r.id} request={r} /> : r.action === 'plan' ? <PlanCard key={r.id} request={r} onAnswer={onAnswer} /> : <ApprovalRow key={r.id} request={r} onAnswer={onAnswer} />))}
                    </div>
                )}
                {turn && (started || !running) && <Foot agentName={agent.name} turn={turn} running={running} failed={failed} from={from} mode={mode} />}
                {cards}
            </div>
            <ReadFold name={agent.name} text={entry.text} />
        </div>
    );
}
