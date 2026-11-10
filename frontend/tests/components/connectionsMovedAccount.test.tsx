// @vitest-environment happy-dom
// An account an agent's move brought over, on the Connections page: its tile and its page say which computer it came
// from, and the page's Remove takes its access away after the dry run names what still uses it.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

const sent = vi.hoisted(() => [] as Record<string, unknown>[]);
vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: vi.fn(async (event: Record<string, unknown>) => {
        sent.push(event);
        return event.confirm ? { success: true } : { success: true, affected_workflows: [{ workflow_id: 'wf_deploy', workflow_name: 'Nightly deploy' }], affected_holders: [] };
    }),
}));
vi.mock('~/lib/socketCall', () => ({ socketCall: vi.fn(async () => ({ shares: [] })) }));
vi.mock('~/hooks/useConnectionProbe', () => ({ useConnectionProbe: () => ({ probe: undefined, check: vi.fn(), canCheck: false }), lastConnectionProbe: () => undefined }));

import { AccountPage } from '~/components/shell/connections/AccountPage';
import { AccountTile } from '~/components/shell/connections/ConnectedList';
import type { ConnectedAccount } from '~/components/shell/connections/accounts';
import type { CredentialInfo } from '~/types/socket-events.generated';

afterEach(() => {
    cleanup();
    sent.length = 0;
});

const credential = (metadata: Record<string, unknown>): CredentialInfo =>
    ({
        id: 'cred_linear_mcp',
        name: 'MCP server linear',
        credential_type: 'mcp_api_key',
        metadata: { server_url: 'https://mcp.linear.app/mcp', ...metadata },
        created_at: '2026-11-08T10:00:00Z',
        updated_at: '2026-11-08T10:00:00Z',
        access_type: 'owner',
    }) as CredentialInfo;

const moved = { move_id: 'mov_studio', host: 'studio-mbp', folder: '~/code/studio', at: '2026-11-08T10:00:00Z', to: { tool_server: 'linear' } };
const account = (metadata: Record<string, unknown>): ConnectedAccount => ({ credential: credential(metadata), app: 'MCP server', line: 'MCP server · mcp.linear.app', source: 'connected' });

describe('an account a move brought over, on the Connections page', () => {
    it('says on its tile which computer it came from', () => {
        render(<AccountTile account={account({ moved_from: moved })} onOpen={() => undefined} />);
        expect(screen.getByTestId('connected-account').textContent).toContain('moved from studio-mbp');
    });

    it('leaves an account that wasn’t moved as it was', () => {
        render(
            <MemoryRouter>
                <AccountTile account={account({})} onOpen={() => undefined} />
                <AccountPage account={account({})} backLabel="Connected" onBack={() => undefined} onGone={() => undefined} />
            </MemoryRouter>
        );
        expect(screen.getByTestId('connected-account').textContent).not.toContain('moved');
        expect(screen.queryByTestId('account-moved')).toBeNull();
        expect(screen.getByTestId('account-page').textContent).toContain('Added Nov 8, 2026');
    });

    it('says where it came from on its page, and removes it after naming what still uses it', async () => {
        const onGone = vi.fn();
        render(
            <MemoryRouter>
                <AccountPage account={account({ moved_from: moved })} backLabel="Connected" onBack={() => undefined} onGone={onGone} />
            </MemoryRouter>
        );
        expect(screen.getByTestId('account-page').textContent).toContain('Moved from studio-mbp · Nov 8');
        const note = screen.getByTestId('account-moved');
        expect(note.textContent).toContain('It came over from studio-mbp, in ~/code/studio on Nov 8');
        fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
        expect((await screen.findAllByText('Remove MCP server linear?')).length).toBeGreaterThan(0);
        await waitFor(() => expect(document.body.textContent).toContain('Nightly deploy'));
        fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
        await waitFor(() => expect(onGone).toHaveBeenCalled());
        expect(sent.map((e) => [e.event_name, e.credential_id, e.confirm])).toEqual([
            ['credential:delete', 'cred_linear_mcp', false],
            ['credential:delete', 'cred_linear_mcp', true],
        ]);
    });
});
