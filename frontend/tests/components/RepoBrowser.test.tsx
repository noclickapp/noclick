// @vitest-environment jsdom
// A repo's page over a fake reader: the root's folders before its files with
// the README under them, a folder and a file opened through ?path= (a folder
// ends in /), a branch switch re-reading at that ref, a binary file named, not
// dumped, a file too big to show named with its size and never read, failures
// said where they happen, an app that deploys the repo opening its own page,
// and a new reader (the repo read again) reading it all again in place.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useSearchParams } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { RepoBrowser, type RepoCommitChanges, type RepoReader, type RepoSummary } from '~/components/shell/resources/RepoBrowser';

afterEach(cleanup);

const NOW = '2026-10-09T12:00:00Z';
const SUMMARY: RepoSummary = { defaultBranch: 'main', sizeBytes: 2048, usedBy: [{ id: 'prj_1', name: 'Shop' }], createdAt: '2026-09-01T00:00:00Z' };

const CART = { sha: '4f2a91c0ffee5d1e2b3a4c5d6e7f8091a2b3c4d5', message: 'Add the cart\n\nThe cart keeps its items across visits.', author: 'Ana', at: '2026-10-09T10:00:00Z' };
const START = { sha: '1b3d5f7a9c0e2f4a6b8d0c1e3f5a7b9d1c3e5f70', message: 'Start the shop', author: 'Ana', at: '2026-10-08T09:00:00Z' };
const BIG = Array.from({ length: 450 }, (_, i) => `+row ${i}`).join('\n');
const CHANGES: Record<string, RepoCommitChanges> = {
    [CART.sha]: {
        ...CART,
        parents: [START.sha],
        additions: 453,
        deletions: 1,
        files: [
            { path: 'data/rows.csv', oldPath: null, status: 'added', additions: 450, deletions: 0, size: 4000, patch: `diff --git a/data/rows.csv b/data/rows.csv\n--- /dev/null\n+++ b/data/rows.csv\n@@ -0,0 +1,450 @@\n${BIG}\n` },
            { path: 'public/logo.png', oldPath: null, status: 'added', additions: null, deletions: null, size: 2048, patch: null },
            {
                path: 'src/app.ts',
                oldPath: null,
                status: 'modified',
                additions: 3,
                deletions: 1,
                size: 60,
                patch: 'diff --git a/src/app.ts b/src/app.ts\n--- a/src/app.ts\n+++ b/src/app.ts\n@@ -1,2 +1,4 @@\n export const app = 1;\n-export const cart = null;\n+import { Cart } from "./cart";\n+export const cart = new Cart();\n+export const total = 0;\n',
            },
        ],
    },
};

function fakeReader({ failCommits = false, longHistory = false } = {}) {
    const reads: string[] = [];
    const reader: RepoReader = {
        branches: async () => ['main', 'feature/cart'],
        async list(dir, ref) {
            reads.push(`list ${ref}:${dir}`);
            if (dir === '') return [
                { path: 'README.md', dir: false, size: 40 },
                { path: 'src', dir: true, size: null },
                { path: 'build.log', dir: false, size: 900_000 },
                ...(ref === 'feature/cart' ? [{ path: 'cart.ts', dir: false, size: 12 }] : []),
            ];
            if (dir === 'src/') return [{ path: 'src/app.ts', dir: false, size: 20 }, { path: 'src/logo.png', dir: false, size: 900 }];
            return [];
        },
        async read(path, ref) {
            reads.push(`read ${ref}:${path}`);
            if (path === 'README.md') return '# Storefront\n\nThe shop.';
            if (path === 'src/app.ts') return 'export const app = 1;\n';
            return null;
        },
        async history(ref, cursor, limit) {
            reads.push(`history ${ref}:${cursor ?? ''}:${limit}`);
            if (failCommits) throw new Error('The repo has no branch, tag or commit.');
            if (!longHistory) return { commits: [CART, START], next: null };
            const from = cursor ? Number(cursor) : 0;
            const all = Array.from({ length: 101 }, (_, i) => ({ ...START, sha: `${String(i).padStart(4, '0')}${START.sha.slice(4)}`, message: `Change ${i}` }));
            return { commits: all.slice(from, from + limit), next: from + limit < all.length ? String(from + limit) : null };
        },
        async commit(sha) {
            reads.push(`commit ${sha}`);
            const found = CHANGES[sha];
            if (!found) throw new Error(`The repo has no commit '${sha}'.`);
            return found;
        },
    };
    return { reader, reads };
}

let location = '';
function Browser({ reader }: { reader: RepoReader }) {
    const [params] = useSearchParams();
    location = params.toString();
    return <RepoBrowser reader={reader} name="storefront" summary={SUMMARY} now={NOW} />;
}

function renderAt(reader: RepoReader, search = '') {
    return render(
        <MemoryRouter initialEntries={[`/${search}`]}>
            <Browser reader={reader} />
        </MemoryRouter>
    );
}

describe('the repo browser', () => {
    it('lists the root, folders first, with its README, the latest commit and what deploys it', async () => {
        const { reader } = fakeReader();
        renderAt(reader);
        const files = await screen.findByRole('list', { name: 'Files' });
        expect(within(files).getAllByRole('button').map((b) => b.textContent)).toEqual(['src', 'build.log879 KB', 'README.md40 B']);
        expect(await screen.findByRole('heading', { name: 'Storefront' })).toBeTruthy();
        expect((await screen.findAllByText('Add the cart')).length).toBeGreaterThan(0);
        expect(screen.getByRole('link', { name: /Shop/ })).toBeTruthy();
    });

    it('opens a folder, then a file, through ?path=, and names a binary file without reading it', async () => {
        const { reader, reads } = fakeReader();
        renderAt(reader);
        fireEvent.click(await screen.findByRole('button', { name: 'src' }));
        await waitFor(() => expect(location).toBe('path=src%2F'));
        fireEvent.click(await screen.findByRole('button', { name: /app\.ts/ }));
        await waitFor(() => expect(location).toBe('path=src%2Fapp.ts'));
        expect(await screen.findByText(/1 line/)).toBeTruthy();
        expect(reads).toContain('read main:src/app.ts');
        // The folder's listing, read once, gave the file its size: opening the file read no listing again.
        expect(reads.filter((r) => r === 'list main:src/')).toHaveLength(1);
        cleanup();
        renderAt(reader, '?path=src/logo.png');
        expect(await screen.findByText(/A binary file, not shown/)).toBeTruthy();
    });

    it('names a file too big to show with its size, read from its folder, and never reads it', async () => {
        const { reader, reads } = fakeReader();
        renderAt(reader, '?path=build.log');
        expect(await screen.findByText('Too big to show here (879 KB). Clone the repo to open it.')).toBeTruthy();
        expect(reads).toContain('list main:');
        expect(reads.some((r) => r.startsWith('read') && r.endsWith('build.log'))).toBe(false);
    });

    it('reads another branch at its own ref, and back on the default drops ?ref=', async () => {
        const { reader, reads } = fakeReader();
        renderAt(reader);
        await screen.findByRole('list', { name: 'Files' });
        await waitFor(() => expect(screen.getByRole('combobox', { name: 'Branch' }).querySelectorAll('option')).toHaveLength(2));
        fireEvent.change(screen.getByRole('combobox', { name: 'Branch' }), { target: { value: 'feature/cart' } });
        await waitFor(() => expect(location).toBe('ref=feature%2Fcart'));
        expect(await screen.findByRole('button', { name: /cart\.ts/ })).toBeTruthy();
        expect(reads).toContain('list feature/cart:');
        fireEvent.change(screen.getByRole('combobox', { name: 'Branch' }), { target: { value: 'main' } });
        await waitFor(() => expect(location).toBe(''));
    });

    it('says when its commits could not be read, with a way to try again', async () => {
        const { reader } = fakeReader({ failCommits: true });
        renderAt(reader);
        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain('The repo has no branch, tag or commit.');
        expect(within(alert).getByRole('button', { name: 'Try again' })).toBeTruthy();
    });

    it("opens an app that deploys it on the app's own page", async () => {
        const { reader } = fakeReader();
        renderAt(reader, '?kind=repos&resource=repo_1&path=src%2F');
        fireEvent.click(await screen.findByRole('link', { name: /Shop/ }));
        await waitFor(() => expect(location).toBe('kind=apps&resource=prj_1'));
    });

    it('counts the history it read, opens it from the latest commit, a day at a time, a message in full on asking', async () => {
        const { reader } = fakeReader();
        renderAt(reader);
        fireEvent.click(await screen.findByRole('button', { name: '2 commits' }));
        await waitFor(() => expect(location).toBe('view=history'));
        const days = await screen.findAllByRole('region', { name: /^Commits on/ });
        expect(days.map((d) => d.getAttribute('aria-label'))).toEqual(['Commits on Oct 9, 2026', 'Commits on Oct 8, 2026']);
        expect(screen.queryByText('The cart keeps its items across visits.')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Show the full message' }));
        expect(screen.getByText('The cart keeps its items across visits.')).toBeTruthy();
        fireEvent.click(within(days[1]).getByRole('button', { name: 'Start the shop' }));
        await waitFor(() => expect(location).toBe(`view=commit&sha=${START.sha}`));
    });

    it('counts a longer history as more than it read, and reads older commits on asking', async () => {
        const { reader, reads } = fakeReader({ longHistory: true });
        renderAt(reader, '?view=history');
        expect(await screen.findByText('100+ commits')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Older commits' }));
        expect(await screen.findByText('101 commits')).toBeTruthy();
        expect(reads).toEqual(expect.arrayContaining(['history main::100', 'history main:100:100']));
        expect(screen.queryByRole('button', { name: 'Older commits' })).toBeNull();
    });

    it('opens a commit: its message, its parent, each file changed with its numbered diff, a binary one named', async () => {
        const { reader } = fakeReader();
        renderAt(reader, `?view=commit&sha=${CART.sha}`);
        expect(await screen.findByRole('heading', { name: 'Add the cart' })).toBeTruthy();
        expect(screen.getByText('The cart keeps its items across visits.')).toBeTruthy();
        expect(screen.getByText('3 files changed')).toBeTruthy();
        const [app] = screen.getAllByTestId('diff');
        const rows = [...app.querySelectorAll('tr')].map((r) => [r.getAttribute('data-line'), ...[...r.querySelectorAll('td')].slice(0, 2).map((td) => td.textContent)]);
        expect(rows).toEqual([
            ['ctx', '1', '1'],
            ['del', '2', ''],
            ['add', '', '2'],
            ['add', '', '3'],
            ['add', '', '4'],
        ]);
        expect(screen.getByText('A binary file (2.0 KB), not shown.')).toBeTruthy();
        // A diff past 400 lines opens folded, a click away.
        const big = screen.getByRole('button', { name: /data\/rows\.csv/ });
        expect(big.getAttribute('aria-expanded')).toBe('false');
        fireEvent.click(big);
        await waitFor(() => expect(screen.getAllByTestId('diff')).toHaveLength(2));
        fireEvent.click(screen.getByRole('button', { name: 'Open commit 1b3d5f7' }));
        await waitFor(() => expect(location).toBe(`view=commit&sha=${START.sha}`));
        expect(await screen.findByRole('alert')).toBeTruthy(); // the fake has no changes for it: said where it happens
    });

    it('walks back up from a commit to the history and the code', async () => {
        const { reader } = fakeReader();
        renderAt(reader, `?view=commit&sha=${CART.sha}`);
        const trail = await screen.findByRole('navigation', { name: 'Where you are' });
        fireEvent.click(within(trail).getByRole('button', { name: 'History' }));
        await waitFor(() => expect(location).toBe('view=history'));
        fireEvent.click(within(await screen.findByRole('navigation', { name: 'Where you are' })).getByRole('button', { name: 'storefront' }));
        await waitFor(() => expect(location).toBe(''));
        expect(await screen.findByRole('list', { name: 'Files' })).toBeTruthy();
    });

    it('reads it all again, in place, when the repo was read again', async () => {
        const first = fakeReader();
        const view = renderAt(first.reader);
        await screen.findByRole('list', { name: 'Files' });
        const again = fakeReader();
        view.rerender(
            <MemoryRouter initialEntries={['/']}>
                <Browser reader={again.reader} />
            </MemoryRouter>
        );
        await waitFor(() => expect(again.reads).toContain('list main:'));
        expect(screen.getByRole('list', { name: 'Files' })).toBeTruthy(); // never back to a skeleton
    });
});
