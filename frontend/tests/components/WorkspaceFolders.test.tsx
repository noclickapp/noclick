// @vitest-environment jsdom
// An agent workspace's page in Resources: its flat listing read as folders,
// each opening in place (`?path=`, ending in /) with a trail back up, files
// opening their preview, and an emptied folder saying so.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { folderListing } from '~/components/shell/resources/fileParts';
import { ResourceDetail } from '~/components/shell/resources/ResourceDetail';
import type { ResourceItem } from '~/components/shell/resources/model';
import type { FileEntry } from '~/components/dashboard/types';

const NOW = '2026-10-16T12:00:00Z';
const FILES = [
    { path: 'notes.md', size: 120, mtime: '2026-10-16T11:00:00Z', url_path: '/agent/workspace/file?token=a' },
    { path: 'reports/2026/q3.csv', size: 4096, mtime: '2026-10-15T09:00:00Z', url_path: '/agent/workspace/file?token=b' },
    { path: 'reports/2026/q2.csv', size: 2048, mtime: '2026-07-01T09:00:00Z', url_path: '/agent/workspace/file?token=c' },
    { path: 'reports/summary.md', size: 900, mtime: '2026-10-16T08:00:00Z', url_path: '/agent/workspace/file?token=d' },
    { path: 'Assets/logo.png', size: 3000, mtime: '2026-09-01T09:00:00Z', url_path: '/agent/workspace/file?token=e' },
];

vi.mock('~/lib/socketCall', () => ({
    socketCall: vi.fn(async () => ({ success: true, workspace: '/workspace', files: FILES })),
}));

afterEach(cleanup);

const entry = (path: string, mtime = NOW): FileEntry => ({ path, size: 10, mtime, kind: 'other' });

describe('a flat listing read as folders', () => {
    it('lists the folders directly in one, by name, with what is under each, then its own files', () => {
        const files = [entry('a.txt'), entry('b/c.txt', '2026-01-01T00:00:00Z'), entry('b/d/e.txt', '2026-02-01T00:00:00Z'), entry('B2/x.txt')];
        const top = folderListing(files, '');
        expect(top.folders.map((f) => [f.name, f.path, f.files, f.mtime])).toEqual([
            ['b', 'b/', 2, '2026-02-01T00:00:00Z'],
            ['B2', 'B2/', 1, NOW],
        ]);
        expect(top.files.map((f) => f.path)).toEqual(['a.txt']);
        const inside = folderListing(files, 'b/');
        expect(inside.folders.map((f) => f.path)).toEqual(['b/d/']);
        expect(inside.files.map((f) => f.path)).toEqual(['b/c.txt']);
    });
});

function Where() {
    const location = useLocation();
    return <output aria-label="Where">{location.search}</output>;
}

const ITEM: ResourceItem = {
    id: 'workspace:w1',
    kind: 'files',
    title: 'Concierge workspace',
    subtitle: 'Bookings',
    updatedAt: NOW,
    usedBy: [],
    workspace: {
        id: 'w1',
        workflow: { id: 'wf1', name: 'Booking', marks: [] },
        agent: { nodeId: 'agent-1', label: 'Concierge', model: 'claude-code' },
        conversationKey: 'default',
        conversationTitle: 'Bookings',
        lastActivity: NOW,
    } as ResourceItem['workspace'],
};

function renderWorkspace(search = '') {
    return render(
        <MemoryRouter initialEntries={[`/dashboard?tab=resources&kind=files&resource=workspace:w1${search}`]}>
            <ResourceDetail item={ITEM} now={NOW} onBack={() => {}} onChanged={() => {}} />
            <Where />
        </MemoryRouter>
    );
}

/** The names the listing shows, folders then files (not the trail's). */
const listed = () =>
    screen
        .getAllByRole('button')
        .filter((b) => !b.closest('nav'))
        .map((b) => b.querySelector('.truncate')?.textContent)
        .filter((name): name is string => !!name);

describe("an agent workspace's page", () => {
    it('opens folders in place and walks back up the trail', async () => {
        renderWorkspace();
        await waitFor(() => expect(listed().length).toBeGreaterThan(0));
        expect(listed()).toEqual(['Assets', 'reports', 'notes.md']);

        fireEvent.click(screen.getByRole('button', { name: /^reports/ }));
        await waitFor(() => expect(screen.getByRole('status', { name: 'Where' }).textContent).toContain('path=reports%2F'));
        expect(listed()).toEqual(['2026', 'summary.md']);
        expect(screen.getByRole('button', { name: /^2026/ }).textContent).toContain('2 files');

        fireEvent.click(screen.getByRole('button', { name: /^2026/ }));
        await waitFor(() => expect(listed()).toEqual(['q3.csv', 'q2.csv']));
        const trail = screen.getByRole('navigation', { name: 'Where you are' });
        expect(trail.textContent).toBe('Files/reports/2026');
        fireEvent.click(within(trail).getByRole('button', { name: 'reports' }));
        await waitFor(() => expect(screen.getByRole('status', { name: 'Where' }).textContent).toContain('path=reports%2F'));
        fireEvent.click(within(screen.getByRole('navigation', { name: 'Where you are' })).getByRole('button', { name: 'Files' }));
        await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Where you are' })).toBeNull());
    });

    it('says a folder that holds nothing any more is empty, with the way back', async () => {
        renderWorkspace('&path=gone%2F');
        expect(await screen.findByText(/Nothing is in gone\/ anymore/)).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'See every file' }));
        await waitFor(() => expect(screen.getByRole('status', { name: 'Where' }).textContent).not.toContain('path='));
    });
});
