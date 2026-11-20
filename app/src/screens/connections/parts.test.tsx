// @vitest-environment happy-dom
// Connections' parts: what a catalog tile and an account's tile say and do, a tab with nothing on it, the proof an
// account works in each of its states, and the account page's name, sharing line and moved note.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { movedFrom, type MovedFrom } from '@/lib/movedFrom';
import { AccountTitle, Moved, sharingLine } from './AccountParts';
import { AccountTile, NoAccounts } from './AccountTile';
import { CatalogTile } from './CatalogTile';
import { Proof, type ConnectionProbe } from './Proof';
import { CONNECTIONS_VIEWS, connectionsAddress, connectionsViews } from './views';

afterEach(cleanup);

/** A move as a credential's metadata records it. */
const moved = (raw: Record<string, string>) => movedFrom(raw) as MovedFrom;

const mark = <span data-testid="mark" />;

describe('a catalog tile', () => {
    const tile = (accounts: { problem?: string }[], idle?: string) => {
        const onManage = vi.fn();
        const onConnect = vi.fn();
        render(<CatalogTile mark={mark} title="Gmail" accounts={accounts} idle={idle} onManage={onManage} onConnect={onConnect} />);
        return { onManage, onConnect };
    };

    it('connects an app with no account, from the tile or its button', () => {
        const { onManage, onConnect } = tile([], 'Subscription');
        expect(screen.getByText('Subscription')).toBeTruthy();
        // The tile and its button both read "Connect Gmail"; the button's click is the button's alone.
        const [tileItself, button] = screen.getAllByRole('button', { name: 'Connect Gmail' });
        fireEvent.click(tileItself);
        fireEvent.click(button);
        expect(onConnect).toHaveBeenCalledTimes(2);
        expect(onManage).not.toHaveBeenCalled();
    });

    it('opens the account you have, and Connect adds another', () => {
        const { onManage, onConnect } = tile([{}]);
        expect(screen.getByText('Connected')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Gmail: open your account' }));
        expect(onManage).toHaveBeenCalledTimes(1);
        fireEvent.click(screen.getByRole('button', { name: 'Connect another Gmail account' }));
        expect(onConnect).toHaveBeenCalledTimes(1);
        expect(onManage).toHaveBeenCalledTimes(1);
    });

    it('counts several accounts, and says when one needs reconnecting', () => {
        tile([{}, {}]);
        expect(screen.getByText('2 accounts')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Gmail: open your accounts' })).toBeTruthy();
        cleanup();
        tile([{}, { problem: 'Disconnected' }]);
        expect(screen.getByText('Needs reconnecting')).toBeTruthy();
    });
});

describe('an account’s tile', () => {
    it('reads whose it is, the account and where it moved from', () => {
        render(
            <AccountTile
                account={{ app: 'Notion', line: 'docs@example.test', sharer: 'Priya Raman', movedFrom: moved({ host: 'studio-mbp' }) }}
                mark={mark}
                onOpen={() => undefined}
            />
        );
        expect(screen.getByTestId('connected-account').textContent).toContain('Priya Raman · docs@example.test · moved from studio-mbp');
        expect(screen.getByRole('button', { name: 'Notion, docs@example.test' })).toBeTruthy();
    });

    it('says what’s wrong, and Reconnect reconnects without opening it', () => {
        const onOpen = vi.fn();
        const onReconnect = vi.fn();
        render(<AccountTile account={{ app: 'Slack', line: 'ops@example.test', problem: 'Disconnected' }} mark={mark} onOpen={onOpen} onReconnect={onReconnect} />);
        expect(screen.getByTestId('connected-account').textContent).toContain('Disconnected');
        expect(screen.getByTestId('connected-account').textContent).not.toContain('ops@example.test');
        fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
        expect(onReconnect).toHaveBeenCalledTimes(1);
        expect(onOpen).not.toHaveBeenCalled();
        fireEvent.click(screen.getByTestId('connected-account'));
        expect(onOpen).toHaveBeenCalledTimes(1);
    });

    it('offers no Reconnect where the host gives none, and a trailing part replaces its own', () => {
        render(<AccountTile account={{ app: 'Slack', line: 'x', problem: 'Disconnected' }} mark={mark} onOpen={() => undefined} />);
        expect(screen.queryByRole('button', { name: 'Reconnect' })).toBeNull();
        cleanup();
        render(<AccountTile account={{ app: 'Slack', line: 'x', problem: 'Disconnected' }} mark={mark} onOpen={() => undefined} onReconnect={() => undefined} trailing={<em>staff</em>} />);
        expect(screen.queryByRole('button', { name: 'Reconnect' })).toBeNull();
        expect(screen.getByText('staff')).toBeTruthy();
    });
});

describe('a tab with no accounts', () => {
    it('offers the catalog on yours alone', () => {
        const onBrowse = vi.fn();
        render(<NoAccounts source="connected" onBrowse={onBrowse} />);
        expect(screen.getByText('No accounts yet')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Browse apps' }));
        expect(onBrowse).toHaveBeenCalled();
        cleanup();
        render(<NoAccounts source="shared" onBrowse={onBrowse} />);
        expect(screen.getByText('Nothing shared with you yet')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Browse apps' })).toBeNull();
    });
});

describe('the proof an account works', () => {
    const proof = (probe: ConnectionProbe | undefined, { canCheck = true, onReconnect }: { canCheck?: boolean; onReconnect?: () => void } = {}) =>
        render(<Proof provider="GitHub" probe={probe} canCheck={canCheck} onReconnect={onReconnect} />).container.textContent;

    it('shows the account’s own things, and how many more', () => {
        const text = proof({ status: 'done', result: { reachable: true, samples: [{ label: 'site' }, { label: 'api' }], total: 5, noun: 'repositories', account_label: 'octo' } });
        expect(text).toContain('Working');
        expect(text).toContain('Your repositories, as GitHub sees them');
        expect(screen.getByTestId('connection-evidence').textContent).toBe('siteapi+3 more');
        expect(text).toContain('Signed in as octo');
    });

    it('says what an answer with nothing to list proves', () => {
        expect(proof({ status: 'done', result: { reachable: true, proves: 'reachability' } })).toContain('GitHub accepted it. It has nothing account-specific to show.');
        cleanup();
        expect(proof({ status: 'done', result: { reachable: true, account_label: 'octo' } })).toContain('Signed in as octo.');
        cleanup();
        expect(proof({ status: 'done', result: { reachable: true } })).toContain('GitHub answered.');
    });

    it('quotes a refusal under NoClick’s hint, with Reconnect where offered', () => {
        const onReconnect = vi.fn();
        const text = proof({ status: 'done', result: { reachable: false, hint: 'Reconnect it.', error: 'Bad credentials' } }, { onReconnect });
        expect(text).toContain('GitHub turned it down');
        expect(text).toContain('Reconnect it.');
        expect(text).toContain('GitHub’s reply');
        expect(text).toContain('Bad credentials');
        fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
        expect(onReconnect).toHaveBeenCalled();
        cleanup();
        expect(proof({ status: 'done', result: { reachable: false, error: 'Bad credentials' } })).not.toContain('reply');
        expect(screen.queryByRole('button', { name: 'Reconnect' })).toBeNull();
    });

    it('never calls an account broken on an answer that isn’t one', () => {
        expect(proof({ status: 'done', result: { reachable: null } })).toContain('No clear answer');
        cleanup();
        expect(proof({ status: 'failed', error: 'Rate limited' })).toContain('this says nothing about the account');
        cleanup();
        expect(proof({ status: 'checking' })).toContain('Asking GitHub…');
        cleanup();
        expect(proof(undefined)).toContain('Asking GitHub…');
        cleanup();
        expect(proof(undefined, { canCheck: false })).toContain('NoClick can’t ask GitHub about this account on its own.');
    });
});

describe('an account page’s parts', () => {
    it('says who else may use it', () => {
        expect(sharingLine([])).toBe('Only you can use it.');
        expect(sharingLine([{ target_type: 'user', target_display_name: 'Sam Lee' }, { target_type: 'organization', target_org_name: 'Acme' }])).toBe(
            'Shared with Sam Lee and everyone in Acme.'
        );
        expect(sharingLine([{ target_type: 'user', target_email: 'a@example.test' }, { target_type: 'user' }, { target_type: 'organization' }, { target_type: 'user' }])).toBe(
            'Shared with a@example.test, someone, and 2 others.'
        );
    });

    it('says where a move brought it from, and only its owner removes it', () => {
        const onRemove = vi.fn();
        render(<Moved moved={moved({ host: 'studio-mbp', folder: '~/code/studio' })} owner onRemove={onRemove} />);
        expect(screen.getByTestId('account-moved').textContent).toContain('It came over from studio-mbp, in ~/code/studio, when an agent moved here.');
        fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
        expect(onRemove).toHaveBeenCalled();
        cleanup();
        render(<Moved moved={moved({})} owner={false} onRemove={onRemove} />);
        expect(screen.getByTestId('account-moved').textContent).toContain('It came over from a computer, when');
        expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
    });

    it('renames in place: Enter and the blur after it save once, Escape and the same name don’t', async () => {
        const onRename = vi.fn(async () => true);
        const title = (renaming: boolean, name = 'Release bot') => (
            <MemoryRouter>
                <AccountTitle name={name} renaming={renaming} onRename={onRename} onDone={() => undefined} />
            </MemoryRouter>
        );
        const { rerender } = render(title(true));
        const input = screen.getByRole('textbox', { name: 'Account name' });
        fireEvent.change(input, { target: { value: '  Deploy bot  ' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        fireEvent.blur(input);
        expect(onRename).toHaveBeenCalledTimes(1);
        expect(onRename).toHaveBeenCalledWith('Deploy bot');
        rerender(title(false));
        // The new name shows until the account comes back renamed.
        expect(screen.getByRole('heading').textContent).toBe('Deploy bot');
        rerender(title(false, 'Deploy bot'));
        expect(screen.getByRole('heading').textContent).toBe('Deploy bot');

        rerender(title(true, 'Deploy bot'));
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'Account name' }), { key: 'Escape' });
        rerender(title(true, 'Deploy bot'));
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'Account name' }), { key: 'Enter' });
        expect(onRename).toHaveBeenCalledTimes(1);
    });

    it('goes back to the name a rename that didn’t take', async () => {
        const onRename = vi.fn(async () => false);
        const { rerender } = render(<AccountTitle name="Release bot" renaming onRename={onRename} onDone={() => undefined} />);
        const input = screen.getByRole('textbox', { name: 'Account name' });
        fireEvent.change(input, { target: { value: 'Deploy bot' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        rerender(<AccountTitle name="Release bot" renaming={false} onRename={onRename} onDone={() => undefined} />);
        await act(async () => undefined);
        expect(screen.getByRole('heading').textContent).toBe('Release bot');
    });
});

describe('the tabs', () => {
    it('show Workspace only in a workspace, and All apps is the page’s bare address', () => {
        expect(connectionsViews(false).map((v) => v.id)).toEqual(['all', 'connected', 'shared']);
        expect(connectionsViews(true).map((v) => v.id)).toEqual(CONNECTIONS_VIEWS.map((v) => v.id));
        expect(connectionsAddress('all')).toEqual({ view: null, account: null });
        expect(connectionsAddress('shared')).toEqual({ view: 'shared', account: null });
    });
});
