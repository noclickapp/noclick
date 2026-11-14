// @vitest-environment happy-dom
// An agent's question in its channel with answers to tap (a WhatsApp agent's first word: answer everyone, or only
// you): a tap posts that answer as yours, which wakes the agent there; once you've said something next, the pick
// reads back and the answers go.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MessageList } from '~/components/shell/channels/MessageList';
import type { Channel, ChannelMessage } from '~/components/shell/channels/types';
import { TooltipProvider } from '~/components/ui/tooltip';

afterEach(cleanup);

const OPTIONS = [
    { label: 'Everyone', reply: 'Answer everyone who messages this number.' },
    { label: 'Only you', reply: 'Answer only me.' },
];
const agent = { id: 'm-1', kind: 'agent' as const, name: 'WhatsApp', agentId: 'a-1', hue: 'sky' as const };
const channel: Channel = { id: 'ch-1', name: 'whatsapp', topic: '', mode: 'all', status: 'open', haltReason: null, workspaceId: null, members: [agent], unread: 0, createdAt: '2026-11-14T09:00:00Z' };
const asked: ChannelMessage = {
    id: 'msg-1',
    author: { type: 'agent', id: 'a-1', name: 'WhatsApp' },
    text: 'I’m on +12025550101 now. Should I answer everyone who messages it, or only you? Until you pick, I answer everyone.',
    at: '2026-11-14T09:00:00Z',
    attachments: [],
    reactions: [],
    mentions: [],
    question: { options: OPTIONS },
};
const yours = (text: string): ChannelMessage => ({ ...asked, id: `you-${text}`, author: { type: 'account', id: null, name: '' }, text, at: '2026-11-14T09:01:00Z', question: undefined });

function show(messages: ChannelMessage[], onAnswer?: (text: string) => void) {
    return render(
        <TooltipProvider>
            <MessageList
                channel={channel}
                schedules={[]}
                messages={messages}
                members={[agent]}
                user={{ name: 'Dhruv', email: 'd@example.com' } as never}
                channels={new Map()}
                older={false}
                loadingOlder={false}
                onLoadOlder={() => undefined}
                onChannel={() => undefined}
                onReact={() => undefined}
                onDismiss={() => undefined}
                actions={{ onAnswer }}
            />
        </TooltipProvider>
    );
}

describe('an agent’s question in its channel', () => {
    it('posts the answer tapped as yours', () => {
        const onAnswer = vi.fn();
        show([asked], onAnswer);
        fireEvent.click(screen.getByRole('button', { name: 'Only you' }));
        expect(onAnswer).toHaveBeenCalledWith('Answer only me.');
        expect(screen.getByRole('button', { name: 'Everyone' })).toBeTruthy();
    });

    it('reads back the pick once you answered, and leaves no answers to tap', () => {
        show([asked, yours('Answer everyone who messages this number.')], vi.fn());
        expect(screen.getByTestId('question-picked').textContent).toBe('You picked everyone');
        expect(screen.queryByRole('button', { name: 'Only you' })).toBeNull();
    });

    it('answered in your own words, the answers just go', () => {
        show([asked, yours('Only my sister and me, please.')], vi.fn());
        expect(screen.queryByTestId('question-picked')).toBeNull();
        expect(screen.queryByRole('button', { name: 'Everyone' })).toBeNull();
    });
});
