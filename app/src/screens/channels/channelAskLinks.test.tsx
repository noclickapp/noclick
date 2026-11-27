// @vitest-environment happy-dom
// An agent's reply that names the link one of its ask rows draws shows that ask once, as the row: the link leaves the
// reply's words (words the agent gave it stay, as plain words), and a link no row draws stays a link.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ChannelAsks } from '@/screens/chat/cards/ChannelAsks';
import { TooltipProvider } from '@/ui/tooltip';
import { MessageList } from './MessageList';
import type { Channel, ChannelMessage } from './types';

afterEach(cleanup);

const GMAIL = 'https://noclick.com/credential/provide/tok-gmail';
const SLACK = 'https://noclick.com/credential/provide/tok-slack';
const agent = { id: 'm-1', kind: 'agent' as const, name: 'Inbox', agentId: 'a-1', hue: 'sky' as const };
const channel: Channel = { id: 'ch-1', name: 'inbox', topic: '', mode: 'all', status: 'open', haltReason: null, workspaceId: null, members: [agent], unread: 0, createdAt: '2026-11-27T09:00:00Z' };
const reply: ChannelMessage = {
    id: 'msg-1',
    author: { type: 'agent', id: 'a-1', name: 'Inbox' },
    text: `I need your Gmail before I can sort it. Connect it here: ${GMAIL}\n\nOnce you [connect Gmail](${GMAIL}) I'll start.\n\nThe Slack link from yesterday still works: ${SLACK}`,
    at: '2026-11-27T09:00:00Z',
    attachments: [],
    reactions: [],
    mentions: [],
    turnAsks: { turn: 'op-1', askedBy: null, asks: [{ kind: 'connect', id: 'op-gmail', credentialType: 'gmail_oauth', label: 'Gmail', url: GMAIL, reason: null, state: null, account: null, by: null }] },
};

it('draws an ask’s link once, as its row, and keeps a link no row draws', () => {
    render(
        <TooltipProvider>
            <MessageList
                channel={channel}
                schedules={[]}
                messages={[reply]}
                members={[agent]}
                user={{ name: 'Ana', email: 'a@example.com' } as never}
                channels={new Map()}
                older={false}
                loadingOlder={false}
                onLoadOlder={() => undefined}
                onChannel={() => undefined}
                onReact={() => undefined}
                onDismiss={() => undefined}
                actions={{ TurnAsks: ({ message }) => <ChannelAsks message={message} answersApprovals={false} onConnected={() => undefined} /> }}
            />
        </TooltipProvider>
    );
    const rows = screen.getByTestId('channel-asks');
    expect(rows.querySelector(`a[href="${GMAIL}"]`)?.textContent).toContain('Connect');
    const links = [...document.querySelectorAll('a[href]')].filter((a) => !rows.contains(a));
    expect(links.map((a) => [a.getAttribute('href'), a.getAttribute('data-link-kind')])).toEqual([[SLACK, 'capability']]);
    expect(screen.getByText('I need your Gmail before I can sort it. Connect it here:')).toBeTruthy();
    expect(screen.getByText("Once you connect Gmail I'll start.")).toBeTruthy();
});
