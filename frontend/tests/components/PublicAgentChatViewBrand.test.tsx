// @vitest-environment jsdom

// A shared agent's public page wears the brand its metadata carries (a
// product's own agents): its name, logo, accent and support link, in place of
// the Powered-by-NoClick badge. Without one the page is NoClick's.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/hooks/useShareSocket', () => ({ useShareSocket: () => ({ socket: null, status: 'connecting' }) }));

import { PublicAgentChatView, type PublicAgentMeta } from '~/components/agent-share/PublicAgentChatView';

afterEach(cleanup);

beforeAll(() => {
    // jsdom has no matchMedia; the composer asks it about the pointer.
    window.matchMedia = ((query: string) =>
        ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} }) as unknown as MediaQueryList);
});

const meta: PublicAgentMeta = {
    workflow_name: 'Support',
    owner_name: null,
    agent: { label: 'Support', model: null },
    tools: [],
    conversation_prefix: 'ck:wf:agent:share:link',
};

describe('PublicAgentChatView', () => {
    it("wears the product's brand", () => {
        const { container } = render(
            <PublicAgentChatView
                linkId="link"
                meta={{ ...meta, brand: { name: 'Acme', logo_url: 'https://acme.example/logo.png', color: '#112233', support_url: 'https://acme.example/help' } }}
                agentIcon={null}
                toolLogos={[]}
            />
        );
        expect(screen.getByTestId('agent-share-brand').textContent).toBe('Acme');
        expect(container.querySelector('[data-brand-accent]')?.getAttribute('style')).toContain('background-color');
        expect(screen.getByRole('link', { name: 'Get help' }).getAttribute('href')).toBe('https://acme.example/help');
        expect(screen.queryByTestId('agent-share-powered-by')).toBeNull();
    });

    it("keeps an unsafe logo or accent off the page, and is NoClick's without a brand", () => {
        const { container } = render(
            <PublicAgentChatView
                linkId="link"
                meta={{ ...meta, brand: { name: 'Acme', logo_url: 'http://acme.example/logo.png', color: 'red', support_url: null } }}
                agentIcon={null}
                toolLogos={[]}
            />
        );
        expect(container.querySelector('[data-testid="agent-share-brand"] img')).toBeNull();
        expect(container.querySelector('[data-brand-accent]')).toBeNull();
        cleanup();
        render(<PublicAgentChatView linkId="link" meta={meta} agentIcon={null} toolLogos={[]} />);
        expect(screen.queryByTestId('agent-share-brand')).toBeNull();
        expect(screen.getByTestId('agent-share-powered-by')).toBeTruthy();
    });
});
