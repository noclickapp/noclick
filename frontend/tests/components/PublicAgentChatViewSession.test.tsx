// @vitest-environment happy-dom

// A platform agent's public page has no New chat: every visitor's chat lands in the agent's one session, so a new
// one would only be a new tag in it. A canvas agent's page (the metadata says nothing) keeps New chat.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/hooks/useShareSocket', () => ({ useShareSocket: () => ({ socket: null, status: 'connecting' }) }));

import { PublicAgentChatView, type PublicAgentMeta } from '~/components/agent-share/PublicAgentChatView';

afterEach(cleanup);

beforeAll(() => {
    window.matchMedia = ((query: string) =>
        ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} }) as unknown as MediaQueryList);
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
});

const meta: PublicAgentMeta = {
    workflow_name: null,
    owner_name: null,
    agent: { label: 'Support', model: null },
    tools: [],
    conversation_prefix: 'ck:wf:agent:share:link',
};

describe('PublicAgentChatView', () => {
    it('offers no new chat on an agent of one session', () => {
        render(<PublicAgentChatView linkId="link" meta={{ ...meta, one_session: true }} agentIcon={null} toolLogos={[]} />);
        expect(screen.getByTestId('agent-share-title').textContent).toBe('Support');
        expect(screen.queryByTestId('agent-share-new-chat')).toBeNull();
    });

    it("keeps New chat on a canvas agent's page", () => {
        render(<PublicAgentChatView linkId="link" meta={meta} agentIcon={null} toolLogos={[]} />);
        expect(screen.getByTestId('agent-share-new-chat').textContent).toContain('New chat');
    });
});
