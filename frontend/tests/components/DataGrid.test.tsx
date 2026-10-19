// @vitest-environment jsdom
// What a resource's records look like on a page: which columns hide their values
// (by the last word of their name, and the sign-in tables' own secrets), how a
// value reads (NULL, bytes by their size, JSON, a timestamp in the reader's
// time), and the grid and record panel built on them: sorting by a header,
// opening a row, and showing a hidden value a cell or a column at a time.
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { binarySize, isSecretColumn, localTime, shownValue } from '~/components/shell/resources/cells';
import { DataGrid, useReveal, type GridColumn, type GridRow } from '~/components/shell/resources/DataGrid';
import { RecordDrawer } from '~/components/shell/resources/RecordDrawer';

afterEach(cleanup);

describe('which columns hide their values', () => {
    it.each([
        ['access_token', true],
        ['accessToken', true],
        ['password', true],
        ['password_hash', true],
        ['api_key', true],
        ['apiKey', true],
        ['client_secret', true],
        ['otp_code', true],
        ['passcode', true],
        ['token_type', false],
        ['access_token_expires_at', false],
        ['tokens_used', false],
        ['country_code', false],
        ['keyboard', false],
        ['monkey', false],
        ['email', false],
    ])('%s → %s', (column, secret) => expect(isSecretColumn(column)).toBe(secret));

    it("hides the sign-in tables' secrets their names don't announce", () => {
        expect(isSecretColumn('value', 'auth_verifications')).toBe(true);
        expect(isSecretColumn('value', 'public.auth_verifications')).toBe(true);
        expect(isSecretColumn('value', 'settings')).toBe(false);
        expect(isSecretColumn('token', 'auth_sessions')).toBe(true);
    });
});

describe('how a value reads', () => {
    it('says NULL, sizes bytes, indents JSON and aligns numbers by type', () => {
        expect(shownValue(null)).toMatchObject({ kind: 'null', text: 'NULL' });
        expect(binarySize('AAEC')).toBe(3);
        expect(binarySize('AAE=')).toBe(2);
        expect(shownValue('AAEC', 'BLOB')).toMatchObject({ kind: 'binary', text: '3 bytes', full: '3 bytes of binary data' });
        expect(shownValue('AAEC', 'text')).toMatchObject({ kind: 'text', text: 'AAEC' });
        expect(shownValue({ a: 1 }, 'jsonb')).toMatchObject({ kind: 'json', text: '{"a":1}', full: '{\n  "a": 1\n}' });
        expect(shownValue('{"marks":[1,2]}', 'text')).toMatchObject({ kind: 'json', full: '{\n  "marks": [\n    1,\n    2\n  ]\n}' });
        expect(shownValue('{not json', 'text').kind).toBe('text');
        expect(shownValue(42, 'integer').kind).toBe('number');
        expect(shownValue('12.50', 'numeric').kind).toBe('number');
        expect(shownValue(true, 'boolean')).toMatchObject({ kind: 'boolean', text: 'true' });
        expect(shownValue('line one\nline two').text).toBe('line one line two');
    });

    it('converts a timestamp to the reader’s time only when it names its zone', () => {
        expect(localTime('2026-10-14T09:12:03.000Z')).toMatch(/2026/);
        expect(localTime('2026-10-14T09:12:03+05:30')).toMatch(/2026/);
        expect(localTime('2026-10-14 09:12:03')).toBeNull();
        expect(localTime('Harbour sprint')).toBeNull();
        expect(localTime(1_760_000_000)).toBeNull();
    });
});

const COLUMNS: GridColumn[] = [
    { name: 'id', type: 'integer' },
    { name: 'email', type: 'text' },
    { name: 'access_token', type: 'text', secret: true },
    { name: 'ghost', type: 'blob' },
];
const ROWS: GridRow[] = [
    { id: 1, email: 'ada@example.com', access_token: 'ya29.first', ghost: 'AAEC' },
    { id: 2, email: null, access_token: 'ya29.second', ghost: null },
];

function Grid({ onSort = () => {}, onOpen = () => {} }: { onSort?: (c: string) => void; onOpen?: (row: number) => void }) {
    const reveal = useReveal('users', 'page-1');
    return <DataGrid label="Rows" columns={COLUMNS} rows={ROWS} sort={{ column: 'id', dir: 'desc' }} onSort={onSort} onOpen={onOpen} reveal={reveal} empty="No rows yet." />;
}

const cells = (row: number) => within(screen.getAllByRole('row')[row + 1]).getAllByRole('cell').map((c) => c.textContent);

describe('a table of records', () => {
    it('shows NULL and bytes for what they are, and each column’s type under its name', () => {
        render(<Grid />);
        expect(cells(0)).toEqual(['', '1', 'ada@example.com', 'hidden', '3 bytes']);
        expect(cells(1)).toEqual(['', '2', 'NULL', 'hidden', 'NULL']);
        expect(screen.getByRole('columnheader', { name: /^id/ }).textContent).toContain('integer');
        expect(screen.getByRole('columnheader', { name: /^id/ }).getAttribute('aria-sort')).toBe('descending');
    });

    it('shows a hidden value when it’s clicked, one cell at a time, or the whole column from its header', () => {
        const opened = vi.fn();
        render(<Grid onOpen={opened} />);
        const [first] = screen.getAllByTitle('Hidden: click to show');
        fireEvent.click(first);
        expect(cells(0)[3]).toBe('ya29.first');
        expect(cells(1)[3]).toBe('hidden');
        // Showing a value doesn't open its row.
        expect(opened).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Show access_token' }));
        expect(cells(1)[3]).toBe('ya29.second');
        fireEvent.click(screen.getByRole('button', { name: 'Hide access_token' }));
        expect([cells(0)[3], cells(1)[3]]).toEqual(['hidden', 'hidden']);
    });

    it('sorts by a header and opens a row from anywhere on it', () => {
        const sorted = vi.fn();
        const opened = vi.fn();
        render(<Grid onSort={sorted} onOpen={opened} />);
        fireEvent.click(within(screen.getByRole('columnheader', { name: /^email/ })).getByRole('button'));
        expect(sorted).toHaveBeenCalledWith('email');
        fireEvent.click(screen.getByText('ada@example.com'));
        fireEvent.click(screen.getByRole('button', { name: 'Open row 2' }));
        expect(opened.mock.calls).toEqual([[0], [1]]);
    });

    it('says what no rows means', () => {
        render(<DataGrid label="Rows" columns={COLUMNS} rows={[]} empty="No rows match this filter." />);
        expect(screen.getByText('No rows match this filter.')).toBeTruthy();
    });
});

describe('a record in full', () => {
    function Drawer() {
        const [shown, setShown] = useState(false);
        return (
            <RecordDrawer
                open
                onOpenChange={() => {}}
                title="auth_accounts"
                description="id acc_1"
                fields={[
                    { name: 'scope', type: 'text', value: 'openid email' },
                    { name: 'refresh_token', type: 'text', value: '1//secret', hidden: !shown, onReveal: () => setShown(true) },
                    { name: 'splits', type: 'text', value: '{"marks":[1,2]}' },
                    { name: 'expires_at', type: 'date', value: '2026-10-14T09:12:03.000Z' },
                    { name: 'image', type: 'text', value: null },
                ]}
                steps={{ where: 'Row 1 of 24', onNext: () => {} }}
            />
        );
    }

    it('shows every field whole, JSON indented, a hidden one when asked, and the rows beside it', () => {
        render(<Drawer />);
        const panel = screen.getByRole('dialog', { name: 'auth_accounts' });
        expect(within(panel).getByText('openid email')).toBeTruthy();
        expect(within(panel).getByText((_, el) => el?.tagName === 'PRE' && el.textContent === '{\n  "marks": [\n    1,\n    2\n  ]\n}')).toBeTruthy();
        expect(within(panel).getByText(/your time$/)).toBeTruthy();
        expect(within(panel).getByText('NULL')).toBeTruthy();
        expect(within(panel).queryByText('1//secret')).toBeNull();
        fireEvent.click(within(panel).getByTitle('Hidden: click to show'));
        expect(within(panel).getByText('1//secret')).toBeTruthy();
        expect((within(panel).getByRole('button', { name: 'Previous row' }) as HTMLButtonElement).disabled).toBe(true);
        expect((within(panel).getByRole('button', { name: 'Next row' }) as HTMLButtonElement).disabled).toBe(false);
        expect(within(panel).getByText('Row 1 of 24')).toBeTruthy();
    });
});
