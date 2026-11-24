// @vitest-environment happy-dom
// A database's query box and its rows keep what's done the moment they're drawn. The rows started over (no row open,
// the first page) in an effect keyed on the result, which React runs a task after the answer lands: a row clicked in
// between opened and closed in one render. The box started over for another database the same way, after that
// database was drawn, taking what was typed into it in between.
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { Database } from 'noclick';
import { afterEach, expect, it } from 'vitest';
import { clickAsDrawn } from '@/lib/clickAsDrawn';
import { fixtureClient } from '@/screens/console/fixtures/client';
import { DATABASES } from '@/screens/console/fixtures/pages/d_data';
import { ClientProvider } from '@/sdk/client';
import { DatabaseBody } from './DatabaseBody';

afterEach(cleanup);

it('opens a row clicked as another query’s rows replace the last one’s', async () => {
    const client = fixtureClient({ set: 'populated' }, { maxRetries: 0 });
    const database = await Database.get(DATABASES[0].id, { client });
    render(
        <ClientProvider client={client}>
            <MemoryRouter initialEntries={['/resources?view=query']}>
                <DatabaseBody database={database} />
            </MemoryRouter>
        </ClientProvider>
    );
    const sql = screen.getByRole('textbox', { name: 'SQL' });
    fireEvent.change(sql, { target: { value: 'select 1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await screen.findByRole('button', { name: 'Open row 1' });

    fireEvent.change(sql, { target: { value: 'select * from bookings limit 3' } });
    const click = clickAsDrawn(() => (screen.queryByRole('button', { name: 'Open row 3' }) ? screen.getByRole('button', { name: 'Open row 2' }) : null));
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(click.clicked()).toBe(true));
    expect(await screen.findByText('Row 2 of 3')).toBeTruthy();
});

it('keeps what’s typed in the query box as another database is drawn', async () => {
    const client = fixtureClient({ set: 'populated' }, { maxRetries: 0 });
    const [booking, other] = await Promise.all(DATABASES.slice(0, 2).map((d) => Database.get(d.id, { client })));
    let show: (database: Database) => void = () => undefined;
    // The database page stays mounted from one database to the next, which a navigation changes, not a click.
    function Page() {
        const [database, setDatabase] = useState(booking);
        show = setDatabase;
        return (
            <>
                <h1>{database.name}</h1>
                <DatabaseBody database={database} />
            </>
        );
    }
    render(
        <ClientProvider client={client}>
            <MemoryRouter initialEntries={['/resources?view=query']}>
                <Page />
            </MemoryRouter>
        </ClientProvider>
    );
    const sql = screen.getByRole('textbox', { name: 'SQL' }) as HTMLTextAreaElement;
    fireEvent.change(sql, { target: { value: 'select 1' } });
    const typed = clickAsDrawn(
        () => (screen.queryByRole('heading', { name: other.name }) ? sql : null),
        (box) => fireEvent.change(box, { target: { value: 's' } })
    );
    show(other);
    await waitFor(() => expect(typed.clicked()).toBe(true));
    await waitFor(() => expect(screen.getByRole('heading', { name: other.name })).toBeTruthy());
    expect(sql.value).toBe('s');
});
