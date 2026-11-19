// An agent session's rows, the one way every page draws them (Work's agent view, the Chat page): a day divider where
// the day changes, a divider where the session was cleared or resumed, your messages, a turn no person started under
// its divider ("A wake-up it set · 8:02") with the whole turn after it, each turn's activity log, reply and cards,
// notes and markers, and the agent's quiet work folded to one line (sources.tsx). What a page adds comes through its
// slots: how a person's message draws (one that came by text as that app did), where it came from (its chip), how a
// note draws, what goes under a turn's reply, and what each row may do (edit from here, open its changes). A page that
// reads what came in on its triggered turns (Work's) draws one a chat app's message started as its own chat
// (ChatTurn), its turn inside it.
import { useEffect, useState, type ReactNode } from 'react';
import { Pencil, RotateCcw, SquarePen } from 'lucide-react';
import type { HarnessRequest, RequestDecision } from 'noclick';
import { failuresTold, type Author, type Entry, type Failure, type NoteEntry, type Thread, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import { fromAnEvent, isChatTurn, type ActivityChat, type TurnActivity } from '@/lib/agentThread/turnActivity';
import type { TurnActivityState } from '../hooks/useTurnActivity';
import { SystemDivider, type ToolCalls } from './Activity';
import { AppTestingLine } from './AppTesting';
import { TurnCardsOf } from './cards';
import { ChatTurn, type ChatAgent } from './ChatTurn';
import { ModelSwitchLine } from './ModelSwitch';
import { MarkerRow, NoteRow, TriggerRow, TurnView, UserRow } from './Rows';
import { QUIET_CHAT, QuietTurn } from './sources';

const TOOL_CALLS_KEY = 'nc-work-tool-calls';

/** How a conversation shows tool calls, on this device: one preference for every page that draws a conversation. */
export function useToolCalls(): [ToolCalls, (mode: ToolCalls) => void] {
    const [mode, setMode] = useState<ToolCalls>('all');
    useEffect(() => {
        try {
            const saved = window.localStorage.getItem(TOOL_CALLS_KEY);
            if (saved === 'all' || saved === 'failures' || saved === 'none') setMode(saved);
        } catch {
            // Storage blocked: Show all.
        }
    }, []);
    return [
        mode,
        (next) => {
            setMode(next);
            try {
                window.localStorage.setItem(TOOL_CALLS_KEY, next);
            } catch {
                // Kept for this visit only.
            }
        },
    ];
}

/** "Today", "Yesterday", "Monday", "3 November". */
export function dayOf(at: number, now = Date.now()): string {
    const day = (t: number) => new Date(t).toDateString();
    if (day(at) === day(now)) return 'Today';
    if (day(at) === day(now - 86_400_000)) return 'Yesterday';
    const ago = (now - at) / 86_400_000;
    return new Date(at).toLocaleDateString('en-US', ago < 6 ? { weekday: 'long' } : { day: 'numeric', month: 'long' });
}

export const atOf = (e: Entry) => (e.kind === 'turn' ? e.startedAt : e.at);

export interface TimelineProps {
    thread: Thread;
    mode: ToolCalls;
    mine: (entry: UserEntry) => boolean;
    onAnswer: (request: HarnessRequest, decision: RequestDecision) => void;
    /** A person's message as this page draws it, where it draws one its own way (undefined: the bubble; null: none,
     *  another row draws it). */
    renderUser?: (entry: UserEntry, index: number) => ReactNode | undefined;
    /** Where a person's message came from, over its bubble (its chip). */
    source?: (entry: UserEntry) => ReactNode;
    /** The agent's name, which its quiet turns' lines start with. */
    agentName?: string;
    /** A note as this page draws it (undefined: the plain note row; null: none, another row draws it). */
    renderNote?: (entry: NoteEntry, index: number) => ReactNode | undefined;
    /** More under a turn's reply, beside its cards. */
    afterReply?: (turn: TurnEntry) => ReactNode;
    /** A turn another row draws (a call's, in its call). */
    hideTurn?: (turn: TurnEntry) => boolean;
    onRewind?: (entry: UserEntry) => void;
    onChanges?: (turn: TurnEntry) => void;
    onReconnect?: (failure: Failure) => void;
    /** Opens what started a turn no person sent (its trigger, on the agent's profile). */
    onTrigger?: (entry: UserEntry) => void;
    /** Opens the agent's profile, where its owner chooses how it works (an app testing line's way there). */
    onProfile?: () => void;
    /** What came in on its triggered turns: one a chat app's message started draws as that chat, with `agent` its
     *  side of it. */
    chats?: { activity: Pick<TurnActivityState, 'byTurn' | 'chats' | 'waiting'>; agent: ChatAgent };
}

/** The chat a triggered message's turn draws as, and what it read of it: its own, or, while its read is on the way,
 *  its chat as another turn's read named it; null for one that keeps its row (a schedule's, a webhook's, one its read
 *  never brought). */
function chatOf(entry: UserEntry, chats: TimelineProps['chats']): { activity: TurnActivity | null; chat: ActivityChat } | null {
    if (!chats || !fromAnEvent(entry)) return null;
    const read = chats.activity.byTurn.get(entry.operationId!);
    if (read) return isChatTurn(read) ? { activity: read, chat: { ...read.chat, avatar: read.chat.avatar ?? chats.activity.chats.get(read.chat.key)?.avatar ?? null } } : null;
    const known = entry.chat ? chats.activity.chats.get(entry.chat) : undefined;
    return chats.activity.waiting.has(entry.operationId!) && known ? { activity: null, chat: known } : null;
}

/** Who moved the session, as its divider names them. */
function moverOf(by: Author | null, mine: TimelineProps['mine']): string | null {
    if (!by) return null;
    if (mine({ author: by } as UserEntry)) return 'you';
    return by.type === 'account' ? 'the account’s owner' : by.name;
}

export function timelineRows({ thread, mode, mine, onAnswer, renderUser, source, agentName = 'It', renderNote, afterReply, hideTurn, onRewind, onChanges, onReconnect, onTrigger, onProfile, chats }: TimelineProps): ReactNode[] {
    const all = Object.values(thread.requests);
    // Requests a turn asked, drawn under it; any whose turn isn't on screen go under the last one.
    const turnOps = new Set(thread.entries.flatMap((e) => (e.kind === 'turn' && e.operationId ? [e.operationId] : [])));
    const lastTurn = [...thread.entries].reverse().find((e): e is TurnEntry => e.kind === 'turn');
    const requestsOf = (turn: TurnEntry): HarnessRequest[] => all.filter((r) => (r.operationId && turnOps.has(r.operationId) ? r.operationId === turn.operationId : turn === lastTurn && r.status === 'pending'));
    let lastDay: string | null = null;
    const rows: ReactNode[] = [];
    // What the person asked in the message a turn answers, for its cards (a trigger's isn't theirs).
    let asked: string | null = null;
    // The turns drawn inside their chat (or their quiet line), and the chat the row before is (its header names it
    // once a run).
    const inChat = new Set<string>();
    let lastChat: string | null = null;
    const turnsByOp = new Map(thread.entries.flatMap((x) => (x.kind === 'turn' && x.operationId ? [[x.operationId, x] as const] : [])));
    // The failed turns a model switch's line beside them already explains.
    const told = failuresTold(thread.entries);
    thread.entries.forEach((e, i) => {
        if (e.kind === 'user') asked = e.trigger && !e.author ? null : e.text;
        const day = dayOf(atOf(e));
        if (day !== lastDay) {
            rows.push(<SystemDivider key={`day:${e.key}`} label={day} />);
            lastDay = day;
        }
        if (e.kind === 'user' && e.chat === QUIET_CHAT && e.operationId) {
            const turn = turnsByOp.get(e.operationId) ?? null;
            inChat.add(e.operationId);
            lastChat = null;
            rows.push(
                <QuietTurn key={e.key} entry={e} turn={turn} name={agentName}>
                    {turn && <TurnView turn={turn} mode={mode} requests={requestsOf(turn)} onAnswer={onAnswer} onReconnect={onReconnect} failureTold={told.has(turn.key)} mine={mine} cards={<TurnCardsOf turn={turn} asked={null} />} />}
                </QuietTurn>
            );
            return;
        }
        const drawn = e.kind === 'user' ? chatOf(e, chats) : null;
        if (drawn && chats && e.kind === 'user') {
            const op = e.operationId!;
            const turn = turnsByOp.get(op) ?? null;
            inChat.add(op);
            rows.push(
                <ChatTurn
                    key={e.key}
                    activity={drawn.activity}
                    chat={drawn.chat}
                    entry={e}
                    turn={turn}
                    agent={chats.agent}
                    header={lastChat !== drawn.chat.key}
                    mode={mode}
                    requests={turn ? requestsOf(turn) : []}
                    onAnswer={onAnswer}
                    onReconnect={onReconnect}
                    failureTold={!!turn && told.has(turn.key)}
                    cards={
                        turn && (
                            <>
                                {afterReply?.(turn)}
                                <TurnCardsOf turn={turn} asked={null} />
                            </>
                        )
                    }
                />
            );
            lastChat = drawn.chat.key;
            return;
        }
        if (!(e.kind === 'turn' && e.operationId && inChat.has(e.operationId))) lastChat = null;
        if (e.kind === 'user') {
            const own = renderUser?.(e, i);
            if (own !== undefined) rows.push(own && <div key={e.key}>{own}</div>);
            // NoClick carrying on once app testing changed: the line it left already says so.
            else if (e.trigger?.kind === 'app_testing' && !e.author) return;
            else rows.push(e.trigger && !e.author ? <TriggerRow key={e.key} entry={e} onOpen={onTrigger ? () => onTrigger(e) : undefined} /> : <UserRow key={e.key} entry={e} mine={mine(e)} source={source?.(e)} onRewind={onRewind && e.id && mine(e) ? () => onRewind(e) : undefined} />);
        } else if (e.kind === 'turn') {
            if (hideTurn?.(e) || (e.operationId && inChat.has(e.operationId))) return;
            const more = afterReply?.(e);
            rows.push(
                <TurnView
                    key={e.key}
                    turn={e}
                    mode={mode}
                    requests={requestsOf(e)}
                    onAnswer={onAnswer}
                    onChanges={onChanges ? () => onChanges(e) : undefined}
                    onRewind={onRewind}
                    onReconnect={onReconnect}
                    failureTold={told.has(e.key)}
                    mine={mine}
                    cards={
                        <>
                            {more}
                            <TurnCardsOf turn={e} asked={asked} />
                        </>
                    }
                />
            );
        } else if (e.kind === 'note') {
            const own = renderNote?.(e, i);
            if (own !== undefined) rows.push(own && <div key={e.key}>{own}</div>);
            else if (e.renamedTo) rows.push(<SystemDivider key={e.key} icon={Pencil} label={`Renamed to ${e.renamedTo}`} />);
            else if (e.appTesting) rows.push(<AppTestingLine key={e.key} note={e.appTesting} agentName={agentName} onProfile={onProfile} />);
            else if (e.modelSwitch) rows.push(<ModelSwitchLine key={e.key} note={e.modelSwitch} agentName={agentName} />);
            else if (e.session) {
                const by = moverOf(e.session.by, mine);
                rows.push(
                    e.session.how === 'cleared' ? (
                        <SystemDivider key={e.key} icon={SquarePen} label="New session" detail={by ? `cleared by ${by}` : undefined} />
                    ) : (
                        <SystemDivider key={e.key} icon={RotateCcw} label="Resumed this session" detail={by ? `by ${by}` : undefined} />
                    )
                );
            } else rows.push(<NoteRow key={e.key} entry={e} />);
        } else rows.push(<MarkerRow key={e.key} entry={e} />);
    });
    return rows;
}

/** The rows, as one element. */
export function Timeline(props: TimelineProps) {
    return <>{timelineRows(props)}</>;
}
