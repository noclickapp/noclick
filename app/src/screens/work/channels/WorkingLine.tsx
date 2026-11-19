// The line over a channel's message box that says who is at it, as a quiet pill left-aligned with the messages: an
// agent at work (its face in Work's working ring, its name, what it's doing now in the words Work uses for a step, and
// for how long), one waiting on you (the needs ring, and an Answer pill to its question), and people typing (their
// face with a typing mark), a person first. A tap opens the agent's turn where Work opens it: the thread it answers
// in, else its profile; waiting on you, its question. Several agents share one line, by their newest step.
import type { ReactNode } from 'react';
import type { AccountMenuUser } from '@/ui/accountParts';
import { useNow } from '@/lib/clock';
import { MemberAvatar } from '@/screens/channels/avatars';
import type { ChannelMember, ChannelMessage } from '@/screens/channels/types';
import { cn } from '@/ui/utils';
import { AgentRing, WorkMotion } from '../agents/AgentRing';
import { elapsed, nowWords, type AgentState } from '../agents/states';
import { channelOfChat } from '../conversation/sessions';
import type { Typist } from '@/screens/channels/typing';

/** Where a tap on the line goes: the thread an agent's turn answers in, the agent (its profile), or a question. */
export type LineTarget = { kind: 'thread'; id: string } | { kind: 'agent'; member: ChannelMember } | { kind: 'question'; messageId: string };

export interface WorkingLineModel {
    /** People typing: their faces (the newest last, wearing the typing mark), who, and "is typing". */
    typing: { faces: ChannelMember[]; names: string; verb: string } | null;
    /** Agents at work, or one waiting on you. */
    agents: {
        faces: ChannelMember[];
        names: string;
        ring: 'working' | 'needs';
        /** The newest step in words, or "is waiting on you". */
        doing: string;
        /** When the shown agent's turn started (ms), for its time; null while it waits on you, or unknown. */
        since: number | null;
        target: LineTarget | null;
        /** An Answer pill: its question is in the channel. */
        answer: boolean;
    } | null;
}

export interface WorkingLineInput {
    channelId: string;
    /** The channel's members as the page draws them. */
    members: readonly ChannelMember[];
    /** Its agents taking a turn here now, as the line shows them. */
    busy: readonly ChannelMember[];
    /** Where the account's agents stand (`agents.states`), where the reader may see it; never a person's. */
    states: readonly AgentState[] | undefined;
    messages: readonly ChannelMessage[];
    /** Who else is typing, still marked. */
    typists: readonly Typist[];
}

const WAITING = 'is waiting on you';
const STILL_WORKING = 'Working';

const listed = (names: string[]) => (names.length > 3 ? `${names.slice(0, 2).join(', ')} and ${names.length - 2} others` : new Intl.ListFormat('en', { type: 'conjunction' }).format(names));
const ms = (iso: string | undefined) => (iso ? Date.parse(iso) || null : null);
/** A person said something: whatever an agent asked before it is answered. */
const persons = (m: ChannelMessage) => !m.ephemeral && (m.author.type === 'user' || (m.author.type === 'account' && !m.author.id));

/** The agent question in the timeline nobody has answered yet, and who asked it. */
function openQuestion(messages: readonly ChannelMessage[], members: readonly ChannelMember[]): { member: ChannelMember; messageId: string } | null {
    for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (persons(m)) return null;
        if (m.question && m.author.type === 'agent') {
            const member = members.find((x) => x.agentId === m.author.id);
            return member ? { member, messageId: m.id } : null;
        }
    }
    return null;
}

/** A typist's face: their member in the channel, else (not in it yet, or the account's owner) their name alone. */
const memberOf = (t: Typist, members: readonly ChannelMember[]) => members.find((m) => m.kind === 'human' && m.userId === t.id);
/** A typist by name: as the change named them, else as the channel's members do (the account's change stream names no
 *  one), else someone not among them yet. */
const nameOf = (t: Typist, members: readonly ChannelMember[]): string => t.name || memberOf(t, members)?.name || 'Someone';
const faceOf = (t: Typist, members: readonly ChannelMember[]): ChannelMember => memberOf(t, members) ?? { id: `typist:${t.id}`, kind: 'human', name: nameOf(t, members) };

/** What the line says now. */
export function workingLineOf({ channelId, members, busy, states, messages, typists }: WorkingLineInput): WorkingLineModel {
    const here = (s: AgentState) => !!s.conversation && channelOfChat(s.conversation) === channelId;
    const typing = typists.length
        ? {
              faces: typists.slice(-3).map((t) => faceOf(t, members)),
              names: typists.length > 3 ? 'Several people' : listed(typists.map((t) => nameOf(t, members))),
              verb: typists.length === 1 ? 'is typing' : 'are typing',
          }
        : null;

    // Waiting on you outranks working, as the agents list orders them: a question in the channel, else a turn here
    // that waits on a person (a held call), whose agent's profile says what.
    const asked = openQuestion(messages, members);
    const held = asked ? null : (states ?? []).find((s) => s.state === 'needs_you' && here(s));
    const waiting = asked?.member ?? (held ? members.find((m) => m.agentId === held.agentId) : undefined);
    if (waiting) {
        const target: LineTarget = asked ? { kind: 'question', messageId: asked.messageId } : { kind: 'agent', member: waiting };
        return { typing, agents: { faces: [waiting], names: waiting.name, ring: 'needs', doing: WAITING, since: null, target, answer: !!asked } };
    }
    if (!busy.length) return { typing, agents: null };

    // Each agent's step, where its state is its turn here; the line says the newest.
    const at = busy.map((member) => {
        const state = member.agentId ? states?.find((s) => s.agentId === member.agentId && s.state === 'working' && here(s)) : undefined;
        const since = ms(member.busySince) ?? state?.turnStartedAt?.getTime() ?? null;
        return { member, since, step: nowWords(state?.now), stepAt: state?.now?.since?.getTime() ?? since ?? 0 };
    });
    const stepping = at.filter((a) => a.step);
    const shown = stepping.length ? stepping.reduce((a, b) => (b.stepAt > a.stepAt ? b : a)) : at[0];
    const { member } = shown;
    const target: LineTarget | null = member.busyThread ? { kind: 'thread', id: member.busyThread } : member.agentId ? { kind: 'agent', member } : null;
    return {
        typing,
        agents: {
            // The shown agent first, so its face leads the stack.
            faces: [member, ...busy.filter((m) => m.id !== member.id)].slice(0, 3),
            names: listed([member, ...busy.filter((m) => m.id !== member.id)].map((m) => m.name)),
            ring: 'working',
            doing: shown.step ?? STILL_WORKING,
            since: shown.since,
            target,
            answer: false,
        },
    };
}

/** Faces overlapped, the first on top. */
function Stack({ children }: { children: ReactNode[] }) {
    return (
        <span className="flex shrink-0 items-center">
            {children.map((child, i) => (
                <span key={i} className={cn('relative inline-flex', i > 0 && '-ml-1.5')} style={{ zIndex: children.length - i }}>
                    {child}
                </span>
            ))}
        </span>
    );
}

/** A person's face with the typing mark: three dots in a small bubble at its corner. */
function TypingFace({ member, user, marked }: { member: ChannelMember; user: AccountMenuUser; marked: boolean }) {
    return (
        <span className="relative inline-flex shrink-0">
            <MemberAvatar member={member} user={user} size={20} className="ring-2 ring-background" />
            {marked && (
                <span aria-hidden data-typing-mark className="absolute -bottom-[5px] -right-[6px] flex h-3 items-center gap-[1.5px] rounded-full bg-secondary px-[3px] ring-2 ring-background">
                    {[0, 160, 320].map((delay) => (
                        <i key={delay} className="work-dot block h-[2.5px] w-[2.5px] rounded-full bg-foreground" style={{ animationDelay: `${delay}ms` }} />
                    ))}
                </span>
            )}
        </span>
    );
}

/** The line, or nothing while nobody is at it. */
export function WorkingLine({ model, user, onOpen }: { model: WorkingLineModel; user: AccountMenuUser; onOpen: (target: LineTarget) => void }) {
    const { typing, agents } = model;
    const now = useNow(agents?.since != null);
    if (!typing && !agents) return null;
    const several = (agents?.faces.length ?? 0) > 1;
    // Said once to a screen reader, without the ticking time.
    const said = [
        typing && `${typing.names} ${typing.verb}`,
        agents && (agents.ring === 'needs' ? `${agents.names} ${WAITING}` : `${agents.names} ${several ? 'are' : 'is'} working: ${agents.doing}`),
    ]
        .filter(Boolean)
        .join('. ');
    const target = agents?.target ?? null;
    const body = (
        <>
            {typing && (
                <span className="flex min-w-0 shrink items-center gap-[7px]" data-testid="channel-typing">
                    <Stack>
                        {typing.faces.map((face, i) => (
                            <TypingFace key={face.id} member={face} user={user} marked={i === typing.faces.length - 1} />
                        ))}
                    </Stack>
                    <span className="ml-0.5 min-w-0 truncate font-medium text-foreground">{typing.names}</span>
                    <span className="shrink-0 whitespace-nowrap">{typing.verb}</span>
                </span>
            )}
            {typing && agents && (
                <span aria-hidden className="shrink-0 text-muted-foreground/60">
                    ·
                </span>
            )}
            {agents && (
                <span className="flex min-w-0 items-center gap-2" data-testid="channel-agents-working">
                    <Stack>
                        {agents.faces.map((face) => (
                            <AgentRing key={face.id} member={face} status={agents.ring} size={20} avatarClassName={several ? 'ring-2 ring-background' : undefined} />
                        ))}
                    </Stack>
                    <span className="ml-0.5 shrink-0 whitespace-nowrap font-medium text-foreground">{agents.names}</span>
                    {agents.ring === 'needs' ? (
                        <span className="shrink-0 whitespace-nowrap">{agents.doing}</span>
                    ) : (
                        // Keyed by the step, so a new one rises in.
                        <span key={agents.doing} className="work-step-in work-shine min-w-0 truncate" data-testid="channel-working-step">
                            {agents.doing}
                        </span>
                    )}
                    {agents.since != null && <span className="shrink-0 tabular-nums">{elapsed(now - agents.since)}</span>}
                    {agents.answer && <span className="ml-0.5 inline-flex h-[22px] shrink-0 items-center rounded-full bg-foreground px-2.5 font-medium text-background">Answer</span>}
                </span>
            )}
        </>
    );
    const pill = 'flex min-w-0 max-w-full items-center gap-2 rounded-full py-1 pl-1 pr-3 text-left text-[12.5px] leading-5 text-muted-foreground';
    return (
        <div className="flex px-4 pb-2" data-testid="channel-working">
            <WorkMotion />
            <span className="sr-only" role="status" aria-live="polite">
                {said}
            </span>
            {target ? (
                <button
                    type="button"
                    onClick={() => onOpen(target)}
                    aria-label={`${said}. ${agents?.answer ? 'Answer' : 'Open its turn'}`}
                    className={cn(pill, 'transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring')}
                >
                    {body}
                </button>
            ) : (
                <div aria-hidden className={pill}>
                    {body}
                </div>
            )}
        </div>
    );
}
