// @vitest-environment happy-dom
// A turn its model connection couldn't run, as its card draws it: what happened ("Your ChatGPT sign-in ended", "Your
// OpenRouter connection is disconnected"), and the way to fix it: the page's own button where the page connects
// accounts itself, else the link the turn's failure carries (the Chat page has no connect flow of its own).
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { failureOf } from '@/lib/agentThread/thread';
import { WorkProviders } from '../agents/fixtures/providers';
import { fakeWorkAgent } from './fixtures/workAgent';
import { RefusedNote } from './Rows';

afterEach(cleanup);

const LINK = 'https://example.test/credential/provide/abc';

function show(failure: ReturnType<typeof failureOf>, onReconnect?: () => void) {
    render(
        <WorkProviders client={fakeWorkAgent().client}>
            <RefusedNote failure={failure!} onReconnect={onReconnect} />
        </WorkProviders>
    );
}

describe('a turn its model connection couldn’t run', () => {
    it('says the connection is disconnected and links to where it’s reconnected', () => {
        const failure = failureOf({
            type: 'credential_disconnected', reason: 'disconnected', connection: 'router', connection_name: 'router',
            integration: 'openrouter', message: "The 'router' connection (OpenRouter) is disconnected.",
            reconnect_url: LINK, line: `I can't answer right now. Reconnect it: ${LINK}`,
        });
        expect(failure).toMatchObject({ reason: 'disconnected', reconnectUrl: LINK, line: expect.stringContaining(LINK) });
        show(failure);
        expect(screen.getByTestId('refused-turn').textContent).toContain('connection is disconnected');
        const link = screen.getByRole('link', { name: /Reconnect/ });
        expect(link.getAttribute('href')).toBe(LINK);
    });

    it('asks a plan to sign in again, at the link, or with the page’s own button where it has one', () => {
        const failure = failureOf({
            type: 'credential_disconnected', reason: 'signed_out', connection: 'credential:c1', connection_name: 'ChatGPT (Codex)',
            integration: 'openai', message: 'The ChatGPT sign-in ended; sign in again to use it.',
            reconnect_url: 'https://example.test/dashboard?tab=connections&view=connected&account=c1',
        });
        show(failure);
        expect(screen.getByTestId('refused-turn').textContent).toContain('Your ChatGPT sign-in ended');
        expect(screen.getByRole('link', { name: /Sign in again/ }).getAttribute('href')).toContain('account=c1');
        cleanup();

        const reconnect = vi.fn();
        show(failure, reconnect);
        expect(screen.queryByRole('link', { name: /Sign in again/ })).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: /Sign in again/ }));
        expect(reconnect).toHaveBeenCalledOnce();
    });
});
