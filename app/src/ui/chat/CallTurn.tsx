// A call with NoClick drawn once where it starts: what each side said on it, how long it ran, and when.
import { useState } from 'react';
import { CallCard, type CallLine } from '@/ui/chat/elsewhere';
import type { CallGroup, SpokenTurn } from '@/ui/chat/channelTurns';
import { PILL_QUIET } from '@/ui/chat/primitives';
import { duration, whenAt } from '@/ui/chat/when';

/** One thing said on a call, as a thread's message has it; its `channel` is how the call came (`whatsapp`, a
 *  `callback`, else a call to NoClick's number). */
export interface CallTurnMessage extends SpokenTurn {
    isUser: boolean;
    text: string;
    sentAt?: number;
}

const CALL_LINES_SHOWN = 8;

export function CallTurn({ call }: { call: CallGroup<CallTurnMessage> }) {
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
