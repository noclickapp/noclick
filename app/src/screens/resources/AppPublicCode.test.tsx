// @vitest-environment happy-dom
// An app's page says whether its code is public: making it public shows the dry run's summary first and refuses to
// go on while it found secrets, a held call says it waits for the owner, a public app shows its clone command and a
// way to make it private, and a copy of someone's public app says where it came from.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ApprovalRequired, type Project, type PublicCode } from 'noclick';
import { AppPublicCode } from './AppPublicCode';

afterEach(cleanup);

function code(over: Partial<PublicCode>): PublicCode {
    return {
        public: false, cloneUrl: 'https://pilot-hub.noclick.site', originUrl: null, commitSha: null, sourceCommit: 'abc1234ffff',
        publishedAt: null, files: 3, license: null, forks: 0, transferCapUsd: 5, blocked: false, wouldPublish: null,
        findings: [], summary: null, raw: {}, ...over,
    };
}

function app(over: Record<string, unknown>, calls: string[] = []): Project {
    return {
        name: 'pilot-hub', url: 'https://pilot-hub.noclick.site', published: false, public: null, forkedFrom: null,
        makePublic: async (options: { dryRun?: boolean } = {}) => {
            calls.push(options.dryRun ? 'dry run' : 'publish');
            return code({ wouldPublish: true, summary: 'Anyone will be able to clone pilot-hub’s code.' });
        },
        makePrivate: async () => {
            calls.push('private');
            return code({ summary: 'Copies stay.' });
        },
        ...over,
    } as unknown as Project;
}

it('shows what would go public before asking, then publishes', async () => {
    const calls: string[] = [];
    render(<AppPublicCode project={app({}, calls)} />);
    expect(screen.getByTestId('app-public-code').textContent).toContain('Only you see its code');
    fireEvent.click(screen.getByRole('button', { name: /Make public/ }));
    await screen.findByText('Anyone will be able to clone pilot-hub’s code.');
    expect(calls).toEqual(['dry run']);
    fireEvent.click(screen.getAllByRole('button', { name: /Make public/ }).at(-1)!);
    await waitFor(() => expect(calls).toEqual(['dry run', 'publish']));
});

it('won’t publish while the dry run found secrets, and names them', async () => {
    const project = app({
        makePublic: async () => code({ wouldPublish: false, summary: 'Anyone…', findings: [{ path: '.env', why: 'its name, .env' }] }),
    });
    render(<AppPublicCode project={project} />);
    fireEvent.click(screen.getByRole('button', { name: /Make public/ }));
    await screen.findByText('.env');
    expect((screen.getAllByRole('button', { name: /Make public/ }).at(-1) as HTMLButtonElement).disabled).toBe(true);
});

it('says a held publish waits for the owner', async () => {
    const project = app({
        makePublic: async (options: { dryRun?: boolean } = {}) => {
            if (options.dryRun) return code({ wouldPublish: true, summary: 'Anyone…' });
            throw new ApprovalRequired('Waits.');
        },
    });
    render(<AppPublicCode project={project} />);
    fireEvent.click(screen.getByRole('button', { name: /Make public/ }));
    await screen.findByText('Anyone…');
    fireEvent.click(screen.getAllByRole('button', { name: /Make public/ }).at(-1)!);
    await screen.findByText(/waits for the account’s owner/);
});

it('shows a public app’s clone command and makes it private', async () => {
    const calls: string[] = [];
    render(<AppPublicCode project={app({ public: code({ public: true, forks: 2, license: 'MIT' }) }, calls)} />);
    const shown = screen.getByTestId('app-public-code').textContent ?? '';
    expect(shown).toContain('git clone https://pilot-hub.noclick.site');
    expect(shown).toContain('2 copies');
    expect(shown).toContain('Licensed MIT');
    fireEvent.click(screen.getByRole('button', { name: /Make private/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Stop clones/ }));
    await waitFor(() => expect(calls).toEqual(['private']));
});

it('says where a copy came from', () => {
    render(<AppPublicCode project={app({ forkedFrom: { address: 'pilot-hub.noclick.site' } })} />);
    expect(screen.getByTestId('app-public-code').textContent).toContain('Copied from pilot-hub.noclick.site');
});
