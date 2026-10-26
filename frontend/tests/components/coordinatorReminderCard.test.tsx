// @vitest-environment jsdom
// A reminder's card reads its reminder back: still to come, it says when and can be cancelled; gone off, a one-off
// reads as done; called off, it says so. It used to offer Cancel… after the reminder had gone off. The reminder's
// own message in the thread reads it again.
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync, sendEvent: vi.fn() }));

import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import type { AgentChatMessage } from '~/hooks/useAgentChat';

const ONCE = '11111111-1111-4111-8111-111111111111';
const WEEKLY = '22222222-2222-4222-8222-222222222222';
const DUE = '2026-10-26T01:26:03+00:00';

afterEach(() => {
    cleanup();
    sendEventAsync.mockReset();
});

/** The socket's answer to coordinator:alarms: each asked-for reminder it holds. */
function serve(alarms: Record<string, Record<string, unknown>>) {
    sendEventAsync.mockImplementation(
        async (req: { event_name: string; schedule_ids?: string[] }) => {
            if (req.event_name !== 'coordinator:alarms') return {};
            return {
                alarms: (req.schedule_ids ?? []).flatMap((id) =>
                    alarms[id] ? [{ schedule_id: id, ...alarms[id] }] : []
                ),
            };
        }
    );
}

function setReminder(
    id: string,
    args: Record<string, string>
): AgentChatMessage {
    return {
        isUser: false,
        text: 'Reminder set.',
        isComplete: true,
        steps: [
            {
                id: `call-${id}`,
                kind: 'tool',
                status: 'completed',
                startedAt: 0,
                title: `Calling schedule_alarm(${JSON.stringify(args)})`,
                detail: JSON.stringify({
                    success: true,
                    schedule_id: id,
                    next_run: DUE,
                    message: args.message,
                }),
            },
        ],
    };
}

const STRETCH = setReminder(ONCE, {
    alarm_type: 'countdown',
    delay_or_time: '2m',
    message: 'Stretch',
});
const REVIEW = setReminder(WEEKLY, {
    alarm_type: 'cron',
    delay_or_time: '0 9 * * 1',
    message: 'Weekly review',
});
const thread = (messages: AgentChatMessage[]) => (
    <CoordinatorTranscript
        isStreaming={false}
        errorReason={null}
        messages={messages}
    />
);
const cancelButtons = () =>
    screen.queryAllByRole('button', { name: /^Cancel/ });

it('offers Cancel… while it is still to come, then reads as done once it went off', async () => {
    serve({ [ONCE]: { status: 'scheduled', next_run: DUE } });
    const { rerender } = render(thread([STRETCH]));
    await waitFor(() => expect(sendEventAsync).toHaveBeenCalled());
    expect(screen.getByText(/Checking back .*: Stretch/)).toBeTruthy();
    expect(cancelButtons()).toHaveLength(1);

    // It goes off: its wake-up is queued, and its own message lands in the thread.
    serve({
        [ONCE]: {
            status: 'scheduled',
            next_run: DUE,
            fired_at: '2026-10-26T01:26:04+00:00',
        },
    });
    rerender(
        thread([
            STRETCH,
            { isUser: false, text: 'Time to stretch.', isComplete: true },
        ])
    );
    await screen.findByText(/Reminded you .*: Stretch/);
    expect(cancelButtons()).toHaveLength(0);
    expect(screen.queryByText(/Checking back/)).toBeNull();
});

it('says a reminder was called off, and keeps a repeating one that went off cancellable', async () => {
    serve({
        [ONCE]: { status: 'cancelled', next_run: DUE },
        [WEEKLY]: {
            status: 'scheduled',
            next_run: '2026-11-02T09:00:00+00:00',
            fired_at: '2026-10-26T09:00:01+00:00',
        },
    });
    render(thread([STRETCH, REVIEW]));
    await screen.findByText(/Cancelled: Stretch/);
    expect(
        screen.getByText(/Checking back next .*: Weekly review/)
    ).toBeTruthy();
    expect(cancelButtons()).toHaveLength(1);
});

it('says only what the tool reported where the server can’t read reminders back', async () => {
    sendEventAsync.mockRejectedValue(new Error('unknown event'));
    render(thread([STRETCH]));
    await waitFor(() => expect(sendEventAsync).toHaveBeenCalled());
    expect(screen.getByText(/Checking back .*: Stretch/)).toBeTruthy();
    expect(cancelButtons()).toHaveLength(1);
});

it('says what the tool reported for a reminder set after the last read, until it is read back', async () => {
    serve({ [ONCE]: { status: 'scheduled', next_run: DUE, fired_at: DUE } });
    const { rerender } = render(thread([STRETCH]));
    await screen.findByText(/Reminded you .*: Stretch/);
    // The new card's reminder isn't in the last read: it reads as set, not as ended.
    sendEventAsync.mockImplementation(() => new Promise(() => {}));
    rerender(thread([STRETCH, REVIEW]));
    expect(
        screen.getByText(/Checking back next .*: Weekly review/)
    ).toBeTruthy();
    expect(cancelButtons()).toHaveLength(1);
});
