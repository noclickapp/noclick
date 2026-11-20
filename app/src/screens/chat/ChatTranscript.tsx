// The Chat page's thread drawn as Work draws an agent's session: NoClick's
// work as Work's activity log ("Worked for 43s ›", each step by its kind, the live line while it works), one message
// look, a turn no person started under its divider ("A wake-up it set · 8:02") with the whole turn after it, and its
// quiet work (a check-in, a failed run it looked into, an agent asking for you: the `background` chat) folded to one
// line, never a message to the owner. What only the Chat page's session carries comes through Work's slots: a
// message that came by text, email or a call reads as that app drew it (a call's turns as one call), what a message
// points at as chips, a note setting an automation up as its setup card, a workflow's Approval step that waits as its
// card (Approve, Decline), a space's news as its note, NoClick's own notes (and its triage of an event from before
// quiet work had its own chat) folded into "What NoClick handled", and under a reply its cards, the files it made, the
// app it went back out on, and the account's out-of-funds card where NoClick turned a turn down.
import { useMemo, type ReactNode } from 'react';
import type { MessageTrigger } from 'noclick';
import { useSlot } from '@/slots';
import type { Entry, NoteEntry, Thread, TurnEntry, UserEntry } from '@/lib/agentThread/thread';
import type { CoordinatorToolCall } from '@/lib/toolCalls';
import { CallTurn, type CallTurnMessage } from '@/ui/chat/CallTurn';
import { RepliedOn } from '@/ui/chat/channels';
import { ChatReferenceChip } from '@/ui/chat/references';
import { TurnCardsOf } from '@/screens/work/conversation/cards';
import { UserRow } from '@/screens/work/conversation/Rows';
import { bubbleOf, cameByOf, QUIET_CHAT, repliedOn, viaBubble } from '@/screens/work/conversation/sources';
import { timelineRows, useToolCalls } from '@/screens/work/conversation/Timeline';
import { MESSAGE_FILE } from '@/screens/work/slots';
import { wroteIt } from '@/screens/work/viewer';
import type { SetupCardRef } from './cards/canvases';
import { UpdatesCard } from './cards/inline/updates';
import { SpaceNewsNote } from './cards/SpaceNewsNote';
import { WorkflowApprovalCard } from './cards/WorkflowApprovalCard';
import { CardsProvider, SetupNoteCard } from './cards/toolCards';
import { entriesOf, type NoteMessage, type SignalRef } from './cards/updates';
import { OUT_OF_FUNDS } from './slots';
import { useChatThread } from './thread';

const ACCOUNT = { type: 'account' as const, id: null, name: null };

/** A call's turns, drawn once as one call where it starts: each run of messages said on a call with the replies to them. */
function callRuns(entries: readonly Entry[]): Map<string, { start: string; turns: CallTurnMessage[] }> {
    const runs = new Map<string, { start: string; turns: CallTurnMessage[] }>();
    let run: { start: string; turns: CallTurnMessage[] } | null = null;
    for (const e of entries) {
        if (e.kind === 'user' && e.via === 'call' && !e.trigger) {
            run ??= { start: e.key, turns: [] };
            run.turns.push(bubbleOf(e));
            runs.set(e.key, run);
        } else if (e.kind === 'turn' && run) {
            if (e.reply) run.turns.push({ isUser: false, text: e.reply, sentAt: e.endedAt ?? e.startedAt, channel: 'voice' });
        } else run = null;
    }
    return runs;
}

/** A message one of NoClick's own events sent (a run that failed, an agent asking for you) into the owner's thread, as
 *  they did before quiet work had its chat: its turn is NoClick's triage, a note of its own. One in the quiet chat
 *  folds as quiet work does; a wake-up it set, a schedule's turn, is drawn as Work draws one. */
const triaged = (e: Entry): e is UserEntry => e.kind === 'user' && e.trigger?.kind === 'platform' && !e.author && e.chat !== QUIET_CHAT;

/** The automation an event names (a failed run's, an agent's that asked for you), its notes' entry. */
function signalOf(trigger: MessageTrigger): SignalRef | undefined {
    const data = trigger.event?.data;
    const id = data?.workflow_id;
    const name = data?.workflow_name;
    if (typeof id !== 'string' || typeof name !== 'string') return undefined;
    return { kind: trigger.event?.type === 'workflow.run.failed' ? 'run_failure' : 'agent_message', workflow_id: id, workflow_name: name };
}

/** One of NoClick's own notes: a note it added (no setup to finish, no space's news), or what its triage said. */
interface Noted {
    note: NoteMessage;
    /** The triage's turn, whose cards draw under the run's card. */
    turn?: TurnEntry;
}

interface NoteRun {
    start: string;
    notes: Noted[];
}

/** Runs of NoClick's own notes, folded into one card where they start: a run of more than one, or one with its
 *  triage in it (a lone note it added draws as Work's note). A triage at work, or one that said nothing or failed, is
 *  drawn as Work draws a turn, its event's divider above it. Keyed by every row the card stands for. */
function noteRuns(entries: readonly Entry[]): Map<string, NoteRun> {
    const runs = new Map<string, NoteRun>();
    let run: { notes: Noted[]; keys: string[] } | null = null;
    const close = () => {
        if (run && (run.notes.length > 1 || run.notes.some((n) => n.turn))) {
            const folded = { start: run.keys[0], notes: run.notes };
            for (const key of run.keys) runs.set(key, folded);
        }
        run = null;
    };
    for (let i = 0; i < entries.length; i++) {
        const e = entries[i];
        const next = entries[i + 1];
        if (e.kind === 'note' && !e.setup && !e.space && !e.workflowApproval) {
            run ??= { notes: [], keys: [] };
            run.notes.push({ note: { isUser: false, text: e.text, isComplete: true, notification: true, sentAt: e.at, turnId: e.key } });
            run.keys.push(e.key);
        } else if (triaged(e) && next?.kind === 'turn' && next.status === 'done' && next.reply?.trim()) {
            const signal = e.trigger ? signalOf(e.trigger) : undefined;
            run ??= { notes: [], keys: [] };
            run.notes.push({ note: { isUser: false, text: next.reply, isComplete: true, notification: true, sentAt: next.endedAt ?? next.startedAt, turnId: next.key, ...(signal ? { signal } : {}) }, turn: next });
            run.keys.push(e.key, next.key);
            i++;
        } else close();
    }
    close();
    return runs;
}

/** A run of NoClick's own notes as one card, with the cards its triage's calls draw under it. */
function NoteFold({ run }: { run: NoteRun }) {
    return (
        <div className="px-1 pt-4" data-note="handled">
            <UpdatesCard entries={entriesOf(run.notes.map((n) => n.note))} />
            {run.notes.map((n) => n.turn && <TurnCardsOf key={n.turn.key} turn={n.turn} asked={null} />)}
        </div>
    );
}

const setupId = (note: NoteEntry) => `setup:${note.key}`;

/** Every card in thread order, for the newest about each automation to draw in full: notes' setups and turns' calls. */
function cardsOf(thread: Thread, calls: ReadonlyMap<string, CoordinatorToolCall[]>): (CoordinatorToolCall | SetupCardRef)[] {
    return thread.entries.flatMap((e): (CoordinatorToolCall | SetupCardRef)[] => (e.kind === 'note' && e.setup ? [{ id: setupId(e), setup: e.setup }] : e.kind === 'turn' ? (calls.get(e.key) ?? []) : []));
}

/** What a turn made beside its words: pictures and videos in place, any other file as a card. */
function MadeFiles({ turn }: { turn: TurnEntry }) {
    const ChatFileCard = useSlot(MESSAGE_FILE);
    if (!turn.files.length) return null;
    return (
        <div className="mt-3 flex flex-wrap gap-1.5" data-testid="coordinator-made-files">
            {turn.files.map((f) =>
                f.kind === 'image' ? (
                    <img key={f.url} src={f.url} alt={f.name} className="max-h-[400px] rounded-lg object-contain" />
                ) : f.kind === 'video' ? (
                    // A video an agent made carries no captions to give it.
                    // eslint-disable-next-line jsx-a11y/media-has-caption
                    <video key={f.url} src={f.url} controls className="max-h-[400px] w-full rounded-lg bg-background object-contain" />
                ) : (
                    <ChatFileCard key={f.url} name={f.name} url={f.url} mimeType={f.mimeType} sizeBytes={f.sizeBytes ?? undefined} />
                )
            )}
        </div>
    );
}

export function ChatTranscript() {
    const { state, jobs, turns, referenceDisplay } = useChatThread();
    const { thread } = state;
    const [mode] = useToolCalls();
    const calls = useMemo(() => {
        const byTurn = new Map<string, CoordinatorToolCall[]>();
        thread.entries.filter((e): e is TurnEntry => e.kind === 'turn').forEach((t, i) => byTurn.set(t.key, [...(turns[i]?.calls ?? [])]));
        return byTurn;
    }, [thread, turns]);
    const cards = useMemo(() => cardsOf(thread, calls), [thread, calls]);
    const callsAt = useMemo(() => callRuns(thread.entries), [thread]);
    const notesAt = useMemo(() => noteRuns(thread.entries), [thread]);
    // The app each turn's reply went back on: the one its message came by.
    const cameBy = useMemo(() => cameByOf(thread), [thread]);
    const OutOfFunds = useSlot(OUT_OF_FUNDS);

    const chipsOf = (e: UserEntry): ReactNode =>
        e.references.length > 0 &&
        e.references.map((r) => {
            const shown = referenceDisplay(r);
            return <ChatReferenceChip key={`${r.kind}:${r.id}`} reference={shown ? { ...r, label: shown.label } : r} mark={shown?.mark} />;
        });

    const rows = timelineRows({
        thread,
        mode,
        mine: (e) => wroteIt(e.author, ACCOUNT),
        agentName: 'NoClick',
        onAnswer: (r, d) => void state.answer(r, d),
        renderUser: (e) => {
            const call = callsAt.get(e.key);
            if (call) return call.start === e.key ? <CallTurn call={{ start: 0, turns: call.turns }} /> : null;
            const run = notesAt.get(e.key);
            if (run) return run.start === e.key ? <NoteFold run={run} /> : null;
            const bubble = viaBubble(e);
            if (bubble !== undefined) return bubble;
            if (e.references.length) return <UserRow entry={e} mine={wroteIt(e.author, ACCOUNT)} chips={chipsOf(e)} />;
            return undefined;
        },
        renderNote: (n) => {
            if (n.setup)
                return (
                    <div className="px-1 pt-4" data-note="setup">
                        <p className="text-[15px] leading-relaxed text-foreground/80">{n.text}</p>
                        <SetupNoteCard id={setupId(n)} setup={n.setup} />
                    </div>
                );
            if (n.space) return <SpaceNewsNote msg={{ isUser: false, text: n.text, isComplete: true, notification: true, sentAt: n.at, space: n.space }} />;
            if (n.workflowApproval)
                return (
                    <div className="px-1 pt-4" data-note="workflow-approval">
                        <p className="text-[15px] leading-relaxed text-foreground/80">{n.text}</p>
                        <div className="mt-3">
                            <WorkflowApprovalCard note={n.workflowApproval} />
                        </div>
                    </div>
                );
            const run = notesAt.get(n.key);
            if (!run) return undefined;
            return run.start === n.key ? <NoteFold run={run} /> : null;
        },
        // A call's turns are drawn in its call, a triage's in NoClick's notes.
        hideTurn: (turn) => (cameBy.get(turn.key) === 'call' && turn.status !== 'running') || notesAt.has(turn.key),
        afterReply: (turn) => {
            // It answers on the app of the newest message it took: one that joined it, else the one that started it.
            const app = repliedOn(turn, cameBy);
            return (
                <>
                    {turn.outOfFunds && (
                        <div className="mt-3">
                            <OutOfFunds refusal={turn.outOfFunds} />
                        </div>
                    )}
                    <MadeFiles turn={turn} />
                    {app && <RepliedOn app={app} />}
                </>
            );
        },
    });

    return (
        <CardsProvider cards={cards} jobs={jobs} moved={thread.entries.length}>
            <div className="pb-2" data-testid="chat-transcript">
                {rows}
            </div>
        </CardsProvider>
    );
}
