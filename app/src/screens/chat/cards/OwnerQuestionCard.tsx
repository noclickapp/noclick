// A question asked of the account's owner (an agent's human__ask, or each input of a build's question), under the
// turn that asked it: answered right here, by a tap on one of its options (or, with Something else, in the owner's
// own words), by picking from their own account for a question about it (which repository, team or channel: the
// canvas's own picker, filled from the account), by choosing the connection a workflow step uses or typing a secret
// it needs (the host's form, else its page on NoClick), by filling in a file on the asking agent's machine (a value per
// key, or the whole file, written there and never shown again, with the file a tap away on its machine page), or, for an
// open question, by writing the answer, through the request's own answer route; whatever asked then carries on with it. Answered, expired or withdrawn, it reads back as
// one line. A question to someone else only shows that it waits on them.
import { FileKey, MessageCircleQuestion } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { GlyphTile, InlineCard, PILL_PRIMARY, PILL_QUIET, PILL_SECONDARY, Receipt, Status } from '@/ui/chat/primitives';
import { FIELD } from '@/ui/fields';
import { useHumanRequest, type FileQuestion, type OwnerAnswer } from '@/screens/humans/useHumanRequest';
import { openMachineFile } from '@/screens/work/place';
import { useSlot } from '@/slots';
import { useClient } from '@/sdk/client';
import { QUESTION_PICK, QUESTION_STEP } from '../slots';
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

const fileName = (path: string) => path.slice(path.lastIndexOf('/') + 1);

/** A file on the asking agent's machine, filled in here: a value per key, else the whole file. What's typed goes
 *  straight into the file and is never shown again, to anyone or to the agent's chat. */
function FileAnswer({ file, disabled, onAnswer }: { file: FileQuestion; disabled: boolean; onAnswer: (given: OwnerAnswer) => void }) {
    const [values, setValues] = useState<Record<string, string>>({});
    const [text, setText] = useState('');
    const keys = file.keys ?? [];
    const ready = keys.length ? keys.every((k) => values[k]) : !!text;
    return (
        <form
            className="grid gap-2"
            onSubmit={(e) => {
                e.preventDefault();
                if (ready) onAnswer(keys.length ? { secret_values: values } : { file_content: text });
            }}
        >
            {keys.length ? (
                keys.map((k) => (
                    <label key={k} className="flex items-center gap-2">
                        <span className="w-[40%] min-w-0 truncate font-mono text-[12.5px] text-foreground/85">{k}</span>
                        <input type="password" autoComplete="off" aria-label={k} value={values[k] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))} className={cn(FIELD, 'h-9 flex-1 font-mono text-[13px]')} />
                    </label>
                ))
            ) : (
                <textarea aria-label={`${fileName(file.path)}’s text`} value={text} onChange={(e) => setText(e.target.value)} rows={5} spellCheck={false} placeholder={`What goes in ${fileName(file.path)}`} className={cn(FIELD, 'h-auto py-2.5 font-mono text-[12.5px]')} />
            )}
            <div className="flex flex-wrap items-center gap-2 pt-1">
                <button type="submit" disabled={disabled || !ready} className={PILL_PRIMARY}>
                    Save to {fileName(file.path)}
                </button>
                <button type="button" onClick={() => openMachineFile(file.agent_id, file.path)} className={PILL_QUIET}>
                    See it on its machine
                </button>
            </div>
            <p className="text-[12.5px] leading-snug text-muted-foreground">
                It goes straight into {file.path} where {file.agent_name || 'the agent'} works, and never shows again: not here, and not in what NoClick shows of its work. The agent can use it from its code.
            </p>
        </form>
    );
}

export function OwnerQuestionCard({ call }: { call: CoordinatorToolCall }) {
    const offered = list(call.args, 'options').filter((o): o is string => typeof o === 'string');
    return <OwnerQuestion requestId={str(call.result, 'request_id') ?? ''} asked={str(call.args, 'question')} offered={offered} />;
}

export interface OwnerQuestionProps {
    /** The human request (`/v1/humans/requests/{id}`). */
    requestId: string;
    /** What it asks and offers, until the request is read. */
    asked?: string;
    offered?: readonly string[];
}

/** One question to the owner, read and answered through its request. */
export function OwnerQuestion({ requestId, asked: askedBefore, offered = [] }: OwnerQuestionProps) {
    const { question, unreadable, answering, failure, answer } = useHumanRequest(useClient(), requestId);
    const Pick = useSlot(QUESTION_PICK);
    const Step = useSlot(QUESTION_STEP);
    // An answer that isn't one of the options, written under the card.
    const [inWords, setInWords] = useState(false);
    const asked = question?.message || askedBefore || 'A question';
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
    if (status === 'answered' && question?.connect) {
        const only = question.answered_by === 'account' ? ' · the only one in your account' : '';
        return <Receipt>{question.connect.label} · {given?.account || given?.choice || given?.connection}{only}</Receipt>;
    }
    if (status === 'answered' && question?.secret) return <Receipt>Kept as {given?.secret || question.secret.name}</Receipt>;
    if (status === 'answered' && question?.file) {
        const keys = given?.keys ?? question.file.keys;
        return <Receipt>Saved to {question.file.path}{keys?.length ? ` · ${keys.join(', ')}` : ''}</Receipt>;
    }
    if (status === 'answered') return <Receipt>You answered · {given?.choices?.join(', ') || given?.choice || given?.text || 'answered'}</Receipt>;
    if (status === 'expired') return <Receipt tone="info">Nobody answered in time · {asked}</Receipt>;
    if (status === 'canceled') return <Receipt tone="info">Withdrawn · {asked}</Receipt>;
    if (unreadable && !question) return <Receipt tone="info">Asked · {asked}</Receipt>;

    // Only a question the signed-in owner may answer (theirs) is answered here; anyone else's waits on them.
    const mine = question ? question.owner_can_answer !== false : true;
    const ready = !!question && !answering;
    const pick = question?.pick ?? null;
    const fillsStep = !!(question?.connect || question?.secret);
    const file = question?.file ?? null;
    // A pick's choices are the account's, picked from all of it below rather than from the first few as buttons.
    const choices = !pick && !fillsStep && !file && options && options.length > 0 ? options : null;
    return (
        <div data-testid="owner-question">
            <InlineCard
                lead={
                    <GlyphTile>{file ? <FileKey className="h-4 w-4" /> : <MessageCircleQuestion className="h-4 w-4" />}</GlyphTile>
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
                {mine && file && (
                    <div className="mt-3" data-testid="owner-question-file">
                        <FileAnswer file={file} disabled={!ready} onAnswer={(given) => void answer(given)} />
                    </div>
                )}
                {mine && question && fillsStep && (
                    <div className="mt-3" data-testid="owner-question-step">
                        <Step question={question} onAnswer={(given) => void answer(given)} disabled={!ready} />
                    </div>
                )}
            </InlineCard>
            {/* A written answer stands under the card, never inside it. */}
            {mine && !pick && !fillsStep && !file && (!choices || inWords) && question && (
                <div className="mt-2.5 max-w-[560px]">
                    <OpenAnswer disabled={!ready} focused={inWords} onSend={(text) => void answer({ text })} />
                </div>
            )}
            {failure && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{failure}</p>}
        </div>
    );
}
