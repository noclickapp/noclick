// The card under a turn that placed a phone call through the platform API: the real call, followed live. It ends as
// one line; the summary and the recording are the reply its end wakes the coordinator for.
import { Loader2, Phone } from 'lucide-react';
import { LiveCall } from '@/ui/chat/live';
import { Receipt } from '@/ui/chat/primitives';
import { usePlacedCall } from './usePlacedCall';
import { obj, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { formatPhoneForDisplay } from '@/lib/phoneFormat';

export { isPlacedCall } from './cardMatchers';

export function PlacedCallCard({ call }: { call: CoordinatorToolCall }) {
    const placed = usePlacedCall(str(call.result, 'operation_id') ?? '');
    const live = placed.call;
    const to = formatPhoneForDisplay(live.to ?? str(obj(call.args, 'arguments'), 'to') ?? '');
    if (!live.known) {
        return (
            <Receipt
                tone="info"
                lead={placed.unreadable ? <Phone className="h-4 w-4 shrink-0 text-foreground/60" /> : <Loader2 className="h-4 w-4 shrink-0 animate-spin text-foreground/60" />}
            >
                {placed.unreadable ? `Called ${to}. How it went shows up here when it ends.` : `Calling ${to}…`}
            </Receipt>
        );
    }
    return (
        <LiveCall
            to={to}
            from={live.from && formatPhoneForDisplay(live.from)}
            state={live.state}
            outcome={live.outcome}
            endedByYou={live.endedByYou}
            placedAt={live.placedAt ?? call.startedAt}
            answeredAt={live.answeredAt}
            endedAt={live.endedAt}
            lines={live.lines}
            onHangUp={placed.hangUp}
            hangingUp={placed.hangingUp}
        />
    );
}
