// The coordinator's thread: the chat transcript every agent chat uses, with what's particular to the account's one
// conversation drawn in place. Turns that came in on WhatsApp, iMessage or email read the way that app drew them, a
// call reads as one call, what NoClick handled on its own folds into one card, a reply says which app it went back
// out on, the tools a turn used draw their cards under it (a build on its canvas, a number to pick, an account
// to connect), kept live by reading their jobs back, and a workflow picked on a public page draws its setup card.
import { memo, useCallback, useMemo, useState, type ComponentProps } from 'react';
import { ChatFileCard } from '~/components/chat/ChatReferenceChip';
import { AgentChatTranscript } from '~/components/chat/AgentChatTranscript';
import { CallCard, EmailMessage, EmailReceipt, IMessageMessage, IMessagePhotos, RepliedOn, WhatsAppMessage, WhatsAppVoiceNote, type CallLine } from '~/components/coordinator/inline/channels';
import { PILL_QUIET } from '~/components/coordinator/inline/primitives';
import { UpdatesCard } from '~/components/coordinator/inline/updates';
import type { AgentChatMessage, AgentChatStep } from '~/hooks/useAgentChat';
import { CoordinatorJobsContext, useCoordinatorJobs, type CoordinatorJobs, type ThreadJobs } from '~/hooks/useCoordinatorJobs';
import { furthest, receiptState, useEmailReceipts } from '~/hooks/useEmailReceipts';
import { inboxLink } from '~/components/shell/mailApp';
import type { CoordinatorEmailReply } from '~/types/socket-events.generated';
import { coordinatorToolCalls, type CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import { cn } from '~/lib/utils';
import { CanvasesProvider, newestCanvases, setupCardId } from './canvases';
import { callsOf, readChannelText, readEmailText, type CallGroup, type ChannelMedia } from './channelTurns';
import { clockTime, duration, shortWhen, whenAt } from './format';
import { jobIdsOf, SetupNoteCard, TurnCards, turnWorkDrawing } from './toolCards';
import { outOfFundsCard, TurnAskedProvider } from './toolCardRegistry';
import { entriesOf, updatesOf } from './updates';

// A finished turn's steps never change, so each is read once.
const read = new WeakMap<readonly AgentChatStep[], CoordinatorToolCall[]>();
function toolCallsOf(msg: AgentChatMessage): CoordinatorToolCall[] {
    if (msg.isUser || !msg.steps) return [];
    let calls = read.get(msg.steps);
    if (!calls) {
        calls = coordinatorToolCalls(msg.steps);
        read.set(msg.steps, calls);
    }
    return calls;
}

function Files({ media }: { media: ChannelMedia[] }) {
    return (
        <>
            {media.map((m) => (
                <ChatFileCard key={m.attachmentId} name={m.name || m.label} url={m.url} />
            ))}
        </>
    );
}

function lostLine(lost: string | undefined): string {
    return lost ? `A ${lost} that couldn’t be read` : '';
}

function WhatsAppTurn({ msg }: { msg: AgentChatMessage }) {
    const { text, media, shared, lost } = readChannelText(msg.text);
    const time = msg.sentAt ? clockTime(msg.sentAt) : undefined;
    const voice = media.find((m) => m.kind === 'voice' || m.kind === 'audio');
    if (voice) return <WhatsAppVoiceNote src={voice.url} transcript={voice.text} time={time} />;
    const files = media.filter((m) => m.kind !== 'image');
    return (
        <WhatsAppMessage
            text={text || lostLine(lost) || undefined}
            time={time}
            photos={media.filter((m) => m.kind === 'image').map((m) => m.url)}
            files={files.length ? <Files media={files} /> : undefined}
            shared={shared}
        />
    );
}

function IMessageTurn({ msg }: { msg: AgentChatMessage }) {
    const { text, media, lost } = readChannelText(msg.text);
    const photos = media.filter((m) => m.kind === 'image').map((m) => m.url);
    const files = media.filter((m) => m.kind !== 'image');
    const voice = media.find((m) => m.kind === 'voice' || m.kind === 'audio');
    return (
        <IMessageMessage
            text={text || voice?.text || lostLine(lost) || undefined}
            photo={photos.length ? <IMessagePhotos photos={photos} /> : undefined}
            files={files.length ? <Files media={files} /> : undefined}
        />
    );
}

function EmailTurn({ msg }: { msg: AgentChatMessage }) {
    const { subject, body } = readEmailText(msg.text);
    const { text, media } = readChannelText(body);
    // Mail since its header was kept says who it was from and to; older mail has only the subject in its text.
    const header = msg.email;
    return (
        <EmailMessage
            subject={header ? (header.subject ?? undefined) : subject}
            from={header?.from ?? undefined}
            to={header?.to ?? undefined}
            time={msg.sentAt ? shortWhen(msg.sentAt) : undefined}
            body={text}
            files={media.length ? <Files media={media} /> : undefined}
        />
    );
}

/** What became of the email that carried a reply: as it was read, or as a frame moved it since. */
function ReplyReceipt({ msg, live }: { msg: AgentChatMessage; live?: CoordinatorEmailReply }) {
    const receipt = furthest(msg.emailReply, live)!;
    return (
        <EmailReceipt
            state={receiptState(receipt, msg.sentAt)}
            to={receipt.to}
            subject={receipt.subject}
            reason={receipt.reason}
            error={receipt.error}
            open={inboxLink(receipt.to, receipt.message_id)}
        />
    );
}

const CALL_LINES_SHOWN = 8;

function CallTurn({ call }: { call: CallGroup }) {
    const [all, setAll] = useState(false);
    const first = call.turns[0];
    const last = call.turns[call.turns.length - 1];
    const lines: CallLine[] = call.turns.filter((t) => t.text).map((t) => ({ who: t.isUser ? 'you' : 'noclick', text: t.text }));
    const shown = all ? lines : lines.slice(0, CALL_LINES_SHOWN);
    const title = first.channel === 'whatsapp' ? 'WhatsApp call with NoClick' : first.channel === 'callback' ? 'NoClick called you back' : 'You called NoClick';
    const length = first.sentAt && last.sentAt && last !== first ? duration((last.sentAt - first.sentAt) / 1000) : undefined;
    return (
        <CallCard
            title={title}
            meta={[length, first.sentAt && whenAt(first.sentAt)].filter(Boolean).join(' · ') || undefined}
            lines={shown}
            actions={
                lines.length > CALL_LINES_SHOWN && (
                    <button type="button" className={PILL_QUIET} onClick={() => setAll((v) => !v)}>
                        {all ? 'Show less' : `Show all ${lines.length} lines`}
                    </button>
                )
            }
        />
    );
}

const REPLY_APPS = { whatsapp_text: 'whatsapp', imessage_text: 'imessage', email: 'email' } as const;

/** What the owner asked in the message the reply at `i` answers; null for a reply no message of theirs started. */
function askedBefore(messages: readonly AgentChatMessage[], i: number): string | null {
    const before = messages[i - 1];
    return before?.isUser && !before.trigger ? before.text : null;
}

/** The coordinator's jobs the thread's calls name. */
function useThreadJobs(toolCalls: readonly CoordinatorToolCall[], nudge: unknown): CoordinatorJobs {
    const ids = useMemo(() => jobIdsOf(toolCalls), [toolCalls]);
    return useCoordinatorJobs(ids, nudge);
}

type TranscriptProps = Omit<ComponentProps<typeof AgentChatTranscript>, 'renderMessage' | 'renderAfter' | 'renderWork'> & {
    /** How the cards follow the work the thread started, where it isn't the coordinator's jobs. */
    useJobs?: ThreadJobs;
};

export const CoordinatorTranscript = memo(function CoordinatorTranscript({ useJobs = useThreadJobs, ...props }: TranscriptProps) {
    const { messages } = props;
    const calls = useMemo(() => callsOf(messages), [messages]);
    const updates = useMemo(() => updatesOf(messages), [messages]);
    const toolCalls = useMemo(() => messages.flatMap(toolCallsOf), [messages]);
    const jobs = useJobs(toolCalls, messages.length);
    // Every card about an automation in thread order (a note's setup card, a turn's tool calls): the newest is drawn
    // in full.
    const canvases = useMemo(
        () => newestCanvases(messages.flatMap((msg, i) => [...(msg.setup ? [{ id: setupCardId(i), setup: msg.setup }] : []), ...toolCallsOf(msg)]), jobs),
        [messages, jobs]
    );
    const receipts = useEmailReceipts();

    const renderMessage = useCallback(
        (msg: AgentChatMessage, i: number) => {
            const call = calls.get(i);
            if (call) return call.start === i ? <CallTurn call={call} /> : null;
            const run = updates.get(i);
            if (run) {
                if (run.start !== i) return null;
                // A folded note's cards (a site a wake-up served at a domain) draw under the run's card.
                return (
                    <>
                        <UpdatesCard entries={entriesOf(run.notes)} />
                        {run.notes.map((note, k) => (
                            <TurnCards key={note.turnId ?? k} calls={toolCallsOf(note)} text={note.text} />
                        ))}
                    </>
                );
            }
            if (!msg.isUser || msg.trigger) return undefined;
            if (msg.channel === 'whatsapp_text') return <WhatsAppTurn msg={msg} />;
            if (msg.channel === 'imessage_text') return <IMessageTurn msg={msg} />;
            if (msg.channel === 'email') return <EmailTurn msg={msg} />;
            return undefined;
        },
        [calls, updates]
    );

    const renderAfter = useCallback((msg: AgentChatMessage, i: number) => {
        if (msg.setup) return <SetupNoteCard id={setupCardId(i)} setup={msg.setup} />;
        const app = msg.channel && msg.channel in REPLY_APPS ? REPLY_APPS[msg.channel as keyof typeof REPLY_APPS] : undefined;
        const toolCalls = toolCallsOf(msg);
        // Files the turn made that aren't pictures or videos (those draw in the reply itself).
        const made = msg.attachments ?? [];
        const OutOfFunds = msg.outOfFunds ? outOfFundsCard() : null;
        if (!app && !toolCalls.length && !made.length && !OutOfFunds) return null;
        return (
            <div className={cn(!msg.text && 'mt-1')}>
                {OutOfFunds && msg.outOfFunds && (
                    <div className="mt-3">
                        <OutOfFunds refusal={msg.outOfFunds} />
                    </div>
                )}
                {made.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5" data-testid="coordinator-made-files">
                        {made.map((f) => (
                            <ChatFileCard key={f.url} name={f.name} url={f.url} mimeType={f.mimeType} />
                        ))}
                    </div>
                )}
                {app && msg.text && (msg.emailReply ? <ReplyReceipt msg={msg} live={receipts[msg.emailReply.id]} /> : <RepliedOn app={app} />)}
                <TurnAskedProvider value={askedBefore(messages, i)}>
                    <TurnCards calls={toolCalls} text={msg.text} />
                </TurnAskedProvider>
            </div>
        );
    }, [receipts, messages]);

    return (
        <CoordinatorJobsContext.Provider value={jobs}>
            <CanvasesProvider value={canvases}>
                <AgentChatTranscript {...props} renderMessage={renderMessage} renderAfter={renderAfter} renderWork={turnWorkDrawing()} />
            </CanvasesProvider>
        </CoordinatorJobsContext.Provider>
    );
});
