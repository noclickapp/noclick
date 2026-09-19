// Exercise background agent replies in a mounted chat hook with real browser DOM.
// The isolated transport delivers controlled frames without sending work to an
// account's agents or changing the user's open coordinator conversation.
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { nc } from '~/lib/nc';
import {
    useAgentChat,
    type AgentChatTransport,
    type UseAgentChatResult,
} from '~/hooks/useAgentChat';
import { agentChatSessionStore } from '~/lib/agentChatSessionStore';
import type { ChatMessageEvent } from '~/types/socket-events.generated';

export default async function () {
    const cid = `coordinator:browser-test-${Date.now()}`;
    let hear: ((event: ChatMessageEvent) => void) | undefined;
    const transport: AgentChatTransport = {
        onEvent: (event, handler) => {
            if (event === 'chat:message')
                hear = handler as (event: ChatMessageEvent) => void;
            return () => {};
        },
        resume: async () => ({ messages: [] }),
    };
    let chat: UseAgentChatResult;
    function Harness() {
        chat = useAgentChat(cid, transport);
        return createElement(
            'div',
            { 'data-streaming': String(chat.isStreaming) },
            ...chat.messages.map((m, i) =>
                createElement('p', { key: i }, m.text)
            )
        );
    }
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
        flushSync(() => root.render(createElement(Harness)));
        await nc.wait.until(() => !!hear, 3000);
        flushSync(() => chat.addUserMessage('What next?'));
        flushSync(() => hear!({ conversation_id: cid, message: 'Next, ' }));
        const result = {
            conversation_id: cid,
            message: 'Researcher replied: Found it.',
            notification: true,
            turn_id: 'coordinator-task:browser-test',
            finished: true,
        };
        flushSync(() => hear!(result));
        nc.assert.equal(
            host.firstElementChild?.getAttribute('data-streaming'),
            'true',
            'Background result must not stop streaming'
        );
        flushSync(() =>
            hear!({
                conversation_id: cid,
                message: 'review it.',
                finished: true,
            })
        );
        flushSync(() => hear!(result));
        const messages = [...host.querySelectorAll('p')].map(
            (p) => p.textContent
        );
        nc.assert.deepEqual(
            messages,
            ['What next?', 'Next, review it.', result.message],
            'Reply stays separate and deduplicates'
        );
        nc.assert.equal(
            host.firstElementChild?.getAttribute('data-streaming'),
            'false',
            'Coordinator completion stops streaming'
        );
        return { messages, duplicateReplies: 0, streamingFinished: true };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
        delete agentChatSessionStore.sessions[cid];
    }
}
