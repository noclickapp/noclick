// A question the agent asked the owner (human__ask), under the turn that asked it: answered right here, by a tap on
// one of its options (or, with Something else, in the owner's own words), by picking from their own account for a
// question about it (which repository, team or channel: the canvas's own picker, filled from the account), or, for
// an open question, by writing the answer, through the request's own answer route; the agent's next turn then carries
// on with it. Answered, expired or withdrawn, it reads back as one line. A question to someone else only shows that it
// waits on them.
import { MessageCircleQuestion } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { GlyphTile, InlineCard, PILL_PRIMARY, PILL_QUIET, PILL_SECONDARY, Receipt, Status } from '@/ui/chat/primitives';
import { FIELD } from '@/ui/fields';
import { useHumanRequest } from '@/screens/humans/useHumanRequest';
import { useSlot } from '@/slots';
import { useClient } from '@/sdk/client';
import { QUESTION_PICK } from '../slots';
import { list, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { cn } from '@/ui/utils';

/** `focused`: opened by the owner's own tap (Something else), so the field takes the focus it asked for. */
function OpenAnswer({ disabled, focused = false, onSend }: { disabled: boolean; focused?: boolean; onSend: (text: string) => void }) {
    const [text, setText] = useState('');
    const field = useRef<HTMLInputElement>(null);
    useEffect(() => {
        if (focused) field.current?.focus();
    }, [focused]);
    return (
        <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
                e.preventDefault();
                if (text.trim()) onSend(text.trim());
            }}
        >
            <input
                ref={field}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Your answer"
                aria-label="Your answer"
                className={cn(FIELD, 'min-w-0 flex-1')}
            />
            <button type="submit" className={PILL_PRIMARY} disabled={disabled || !text.trim()}>
                Send
            </button>
        </form>
    );
}

export function OwnerQuestionCard({ call }: { call: CoordinatorToolCall }) {
    const { question, unreadable, answering, failure, answer } = useHumanRequest(useClient(), str(call.result, 'request_id') ?? '');
    const Pick = useSlot(QUESTION_PICK);
    // An answer that isn't one of the options, written under the card.
    const [inWords, setInWords] = useState(false);
    const asked = question?.message || str(call.args, 'question') || 'A question';
    const offered = list(call.args, 'options').filter((o): o is string => typeof o === 'string');
    const options = question ? question.options : offered;
    const status = question?.status ?? 'pending';
    const given = question?.answer;

    if (status === 'answered' && question?.answered_by === 'account' && question.pick) {
        return (
            <Receipt>
                {question.pick.field_label} · {given?.choice} · the only one in your account
            </Receipt>
        );
    }
    if (status === 'answered') return <Receipt>You answered · {given?.choice || given?.text || 'answered'}</Receipt>;
    if (status === 'expired') return <Receipt tone="info">Nobody answered in time · {asked}</Receipt>;
    if (status === 'canceled') return <Receipt tone="info">Withdrawn · {asked}</Receipt>;
    if (unreadable && !question) return <Receipt tone="info">Asked · {asked}</Receipt>;

    // Only a question the signed-in owner may answer (theirs) is answered here; anyone else's waits on them.
    const mine = question ? question.owner_can_answer !== false : true;
    const ready = !!question && !answering;
    const pick = question?.pick ?? null;
    // A pick's choices are the account's, picked from all of it below rather than from the first few as buttons.
    const choices = !pick && options && options.length > 0 ? options : null;
    return (
        <div data-testid="owner-question">
            <InlineCard
                lead={
                    <GlyphTile>
                        <MessageCircleQuestion className="h-4 w-4" />
                    </GlyphTile>
                }
                title={asked}
                meta={mine ? 'Waiting for your answer' : 'Waiting for their answer'}
                actions={
                    mine && choices ? (
                        <>
                            {choices.map((choice, i) => (
                                <button key={choice} type="button" className={i === 0 ? PILL_PRIMARY : PILL_SECONDARY} disabled={!ready} onClick={() => void answer({ choice })}>
                                    {choice}
                                </button>
                            ))}
                            {!inWords && (
                                <button type="button" className={PILL_QUIET} disabled={!ready} onClick={() => setInWords(true)}>
                                    Something else
                                </button>
                            )}
                        </>
                    ) : undefined
                }
            >
                {!question ? <Status state="working">Checking it’s still waiting</Status> : null}
                {mine && pick && (
                    <div className="mt-3" data-testid="owner-question-pick">
                        <Pick pick={pick} question={asked} onAnswer={(choice) => void answer({ choice })} />
                    </div>
                )}
            </InlineCard>
            {/* A written answer stands under the card, never inside it. */}
            {mine && !pick && (!choices || inWords) && question && (
                <div className="mt-2.5 max-w-[560px]">
                    <OpenAnswer disabled={!ready} focused={inWords} onSend={(text) => void answer({ text })} />
                </div>
            )}
            {failure && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{failure}</p>}
        </div>
    );
}
