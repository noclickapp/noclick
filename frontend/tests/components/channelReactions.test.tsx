// @vitest-environment happy-dom
// A message's reactions on a phone, where no tooltip opens: holding one says who reacted with it (you first, and a way
// to take yours back), and the tap that ends the hold changes nothing; a quick tap still adds or takes back yours; a
// mouse keeps its hover tooltip and never opens the sheet; a finger that moves is scrolling, not holding.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MessageList } from '~/components/shell/channels/MessageList';
import type { Channel, ChannelMessage } from '~/components/shell/channels/types';
import { TooltipProvider } from '~/components/ui/tooltip';

const agent = { id: 'm-1', kind: 'agent' as const, name: 'Growth', agentId: 'a-1', hue: 'sky' as const };
const channel: Channel = { id: 'ch-1', name: 'launch', topic: '', mode: 'all', status: 'open', haltReason: null, workspaceId: null, members: [agent], unread: 0, createdAt: '2026-11-14T09:00:00Z' };
const message: ChannelMessage = {
    id: 'msg-1',
    author: { type: 'agent', id: 'a-1', name: 'Growth' },
    text: 'The pricing page is live.',
    at: '2026-11-14T09:00:00Z',
    attachments: [],
    reactions: [{ emoji: '🎉', count: 3, mine: true, names: ['Priya', 'You', 'Sam'] }],
    mentions: [],
};

type OnReact = (messageId: string, emoji: string) => void;
let onReact: ReturnType<typeof vi.fn<OnReact>>;
function show() {
    onReact = vi.fn<OnReact>();
    render(
        <TooltipProvider>
            <MessageList
                channel={channel}
                schedules={[]}
                messages={[message]}
                members={[agent]}
                user={{ name: 'Dhruv', email: 'd@example.com' } as never}
                channels={new Map()}
                older={false}
                loadingOlder={false}
                onLoadOlder={() => undefined}
                onChannel={() => undefined}
                onReact={onReact}
                onDismiss={() => undefined}
            />
        </TooltipProvider>
    );
    return screen.getByRole('button', { name: '🎉 3, yours' });
}

const press = (chip: HTMLElement, pointerType: string) => fireEvent.pointerDown(chip, { pointerType, clientX: 10, clientY: 10 });
const release = (chip: HTMLElement) => {
    fireEvent.pointerUp(chip);
    fireEvent.click(chip);
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('a reaction held on a phone', () => {
    it('says who reacted, you first, and the tap that ends the hold changes nothing', () => {
        const chip = show();
        press(chip, 'touch');
        act(() => vi.advanceTimersByTime(500));
        const sheet = screen.getByTestId('reacted-sheet');
        expect(sheet.textContent).toContain('Who reacted');
        expect(sheet.textContent).toContain('🎉');
        expect([...sheet.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['You', 'Priya', 'Sam']);
        release(chip);
        expect(onReact).not.toHaveBeenCalled();
    });

    it('takes yours back from the sheet', () => {
        const chip = show();
        press(chip, 'touch');
        act(() => vi.advanceTimersByTime(500));
        fireEvent.click(screen.getByRole('button', { name: 'Remove yours' }));
        expect(onReact).toHaveBeenCalledWith('msg-1', '🎉');
        expect(screen.queryByTestId('reacted-sheet')).toBeNull();
    });

    it('still adds or takes back yours on a quick tap', () => {
        const chip = show();
        press(chip, 'touch');
        act(() => vi.advanceTimersByTime(150));
        release(chip);
        act(() => vi.advanceTimersByTime(500));
        expect(onReact).toHaveBeenCalledWith('msg-1', '🎉');
        expect(screen.queryByTestId('reacted-sheet')).toBeNull();
    });

    it('leaves a mouse to its tooltip, and a moving finger to its scroll', () => {
        const chip = show();
        press(chip, 'mouse');
        act(() => vi.advanceTimersByTime(500));
        expect(screen.queryByTestId('reacted-sheet')).toBeNull();
        press(chip, 'touch');
        fireEvent.pointerMove(chip, { pointerType: 'touch', clientX: 10, clientY: 40 });
        act(() => vi.advanceTimersByTime(500));
        expect(screen.queryByTestId('reacted-sheet')).toBeNull();
    });
});
