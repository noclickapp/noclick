// @vitest-environment jsdom
// An automation's tables on its database page: a table opens a level down
// (`?table=`) with its rows a page at a time from the Table block's own event,
// each row in full, secret-looking values hidden until asked, and every row as
// CSV; Back on the trail returns to the list.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ResourceDetail } from '~/components/shell/resources/ResourceDetail';
import type { ResourceItem } from '~/components/shell/resources/model';

const NOW = '2026-10-16T12:00:00Z';
const ROWS = Array.from({ length: 120 }, (_, i) => ({ email: `guest${i + 1}@example.com`, party: (i % 6) + 1, api_key: `sk_live_${i + 1}`, note: i % 4 ? null : 'Window seat' }));

vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: vi.fn(async (event: { event_name: string; resource_id: string; limit: number; offset?: number }) => {
        const offset = event.offset ?? 0;
        return { rows: ROWS.slice(offset, offset + event.limit).map((data, i) => ({ id: `row-${offset + i}`, row_index: offset + i, data })), total_count: ROWS.length };
    }),
}));
import { sendEventAsync } from '~/lib/socket-sender';

afterEach(cleanup);

const next = () => screen.getByText('Next').closest('button') as HTMLButtonElement;

const ITEM: ResourceItem = {
    id: 'tables:wf1',
    kind: 'databases',
    title: 'Guest list',
    subtitle: '1 table · 120 rows',
    updatedAt: NOW,
    usedBy: [],
    tables: [
        {
            entry: { path: 'guests', size: 0, mtime: NOW, kind: 'data', resourceType: 'dataset', resourceId: 'res_guests', rows: 120 },
            source: { id: 'wf1', kind: 'resources', label: 'Guest list', sublabel: 'Tables', files: [] },
        },
    ],
};

/** A column's cells, read off the DOM (role queries over 50 rows are slow in jsdom). */
const column = (name: string) => {
    const table = screen.getByLabelText('Rows of guests');
    const index = [...table.querySelectorAll('thead th')].findIndex((h) => h.textContent?.startsWith(name));
    return [...table.querySelectorAll('tbody tr')].map((row) => row.children[index]?.textContent);
};

describe("an automation's tables", () => {
    it('open their rows a page at a time, each row in full, its secrets hidden until asked', async () => {
        render(
            <MemoryRouter initialEntries={['/dashboard?tab=resources&kind=databases&resource=tables:wf1']}>
                <ResourceDetail item={ITEM} now={NOW} onBack={() => {}} onChanged={() => {}} />
            </MemoryRouter>
        );
        expect(screen.getByText('120 rows')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: /^guests/ }));
        await waitFor(() => expect(column('email')).toHaveLength(50));
        expect(column('email')[0]).toBe('guest1@example.com');
        expect(column('party')[0]).toBe('1');
        expect(column('note')[1]).toBe('NULL');
        expect(column('api_key')[0]).toBe('hidden');
        expect(screen.getByText('Rows 1–50 of 120')).toBeTruthy();

        fireEvent.click(next());
        await waitFor(() => expect(column('email')[0]).toBe('guest51@example.com'));
        expect(vi.mocked(sendEventAsync).mock.calls.at(-1)![0]).toMatchObject({ resource_id: 'res_guests', limit: 50, offset: 50 });

        fireEvent.click(screen.getByLabelText('Open row 1'));
        const panel = await screen.findByRole('dialog', { name: 'guests' });
        expect(within(panel).getByText('Row 51 of 120')).toBeTruthy();
        expect(within(panel).queryByText('sk_live_51')).toBeNull();
        fireEvent.click(within(panel).getByTitle('Hidden: click to show'));
        expect(within(panel).getByText('sk_live_51')).toBeTruthy();
        fireEvent.keyDown(panel, { key: 'Escape' });

        fireEvent.click(within(screen.getByRole('navigation', { name: 'Where you are' })).getByRole('button', { name: 'Tables' }));
        await waitFor(() => expect(screen.queryByRole('table', { name: 'Rows of guests' })).toBeNull());
        expect(screen.getByRole('button', { name: /^guests/ })).toBeTruthy();
    }, 30_000);
});
