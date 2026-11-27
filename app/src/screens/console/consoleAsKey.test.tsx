// @vitest-environment happy-dom
// A console acting as one of the account's keys (as this app's does) asks the API for nothing only the signed-in
// owner may have. NoClick's API refuses a key those operations (ownerOnly.ts lists the ones the console can reach),
// and the fixtures refuse them the same way, 403 `permission_denied`, so a page that still asked would show the
// refusal. This opens every page of the console as a key and fails on any such request, then checks what a key's
// console says and leaves out where the owner's has those things.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi, type MockInstance } from 'vitest';
import { DeveloperConsole } from './DeveloperConsole';
import { openConsolePalette } from './ConsolePalette';
import { AGENTS, FIXTURE_NOW_MS, FIXTURE_USER, KEYS, USERS, type FixtureSet } from './fixtures/core';
import { makeFixtureFetch } from './fixtures/fixtureFetch';
import { LAB_SETUP_CODE } from './fixtures/pages/a';
import { TRY_IT_OPERATION_ID } from './fixtures/pages/b';
import { NEW_IN_CODE, type NewInCodeKind } from './lib/newInCode';
import type { NewKind } from './lib/snippets';
import { CARDS } from './fixtures/pages/h_identity';
import { BOOKING_APP_ID } from './fixtures/pages/e_build';
import { isOwnerOnly, OWNER_ONLY, OWNER_ONLY_OPERATIONS, ownerOnlyWhy, type OwnerOnlyRow } from './ownerOnly';
import { visibleKinds } from './resourceKinds';
import { LOG_VIEWS, SECTIONS, SETTINGS_PAGES } from './sections';

let logged: MockInstance<typeof console.error>;
beforeEach(() => {
    logged = vi.spyOn(console, 'error');
});
afterEach(() => {
    cleanup();
    logged.mockRestore();
});

const BASE = '/developers';

interface Calls {
    /** Every request the console made, as `METHOD /v1/path`. */
    made: string[];
    /** The ones only the signed-in owner may make. */
    ownerOnly: string[];
    /** Resolves once the page is drawn: its code loaded, nothing still loading on it, and no request in flight for a
     *  moment. Fails if the page crashed instead. */
    settled(): Promise<void>;
}

/** A console at `address` (a path under the console, with its query) acting as `actsAs`, over the fixtures' `set`. */
function open(address: string, actsAs: 'owner' | 'key' = 'key', set: FixtureSet = 'populated', lab = false): Calls {
    const answer = makeFixtureFetch({ set, actsAs });
    const made: string[] = [];
    const ownerOnly: string[] = [];
    let flying = 0;
    let last = Date.now();
    const client = new NoClick({
        apiKey: 'a-fixture-holds-no-key',
        baseUrl: DEFAULT_BASE_URL,
        maxRetries: 0,
        fetch: async (input, init) => {
            const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
            const method = (init?.method ?? 'GET').toUpperCase();
            made.push(`${method} ${url.pathname}`);
            if (isOwnerOnly(method, url.pathname)) ownerOnly.push(`${method} ${url.pathname}`);
            flying += 1;
            try {
                return await answer(input, init);
            } finally {
                flying -= 1;
                last = Date.now();
            }
        },
    });
    function Mounted() {
        return (
            <DeveloperConsole
                section={useParams()['*']}
                client={client}
                actsAs={actsAs}
                basePath={BASE}
                apiUrl="https://api.noclick.com"
                site="https://noclick.com"
                home="/"
                user={FIXTURE_USER}
                now={() => FIXTURE_NOW_MS}
                onSignOut={() => undefined}
                live={null}
                lab={lab}
            />
        );
    }
    render(
        <MemoryRouter initialEntries={[`${BASE}${address ? `/${address}` : ''}`]}>
            <Routes>
                <Route path={`${BASE}/*`} element={<Mounted />} />
            </Routes>
        </MemoryRouter>,
    );
    return {
        made,
        ownerOnly,
        // A page loads lazily, reads, and may read again from what it read: it's done once nothing on it says it is
        // still loading and no request has been in flight for a while.
        settled: async () => {
            await waitFor(
                () => {
                    expect(made.length).toBeGreaterThan(0);
                    expect(flying).toBe(0);
                    expect(Date.now() - last).toBeGreaterThan(120);
                    expect([...document.querySelectorAll('[aria-busy]')].filter((el) => el.getAttribute('aria-busy') !== 'false').length).toBe(0);
                },
                { timeout: SETTLE_S, interval: 30 },
            );
            expect(logged.mock.calls.filter(([first]) => String(first).includes('page crashed')).map((call) => String(call[1]))).toEqual([]);
        },
    };
}

// How long a page may take to settle, and each test with it: a page loads its code lazily, which takes seconds while
// the rest of the suite shares the machine. The wait is on the page's state; these only bound a page that never settles.
const SETTLE_S = 20_000;
const TEST_S = 40_000;

/** Every address the console has: its sections and what's inside them, each kind of resource, and its drawers. */
const ADDRESSES = [
    '',
    ...SECTIONS.filter((section) => section.id !== 'home').map((section) => section.id),
    ...LOG_VIEWS.map((view) => `logs/${view.id}`),
    ...SETTINGS_PAGES.map((page) => `settings/${page.id}`),
    ...visibleKinds(false).map((kind) => `resources/${kind.id}`),
    `agents/${AGENTS[0].id}`,
    `users/${USERS[0].id}`,
    `logs?op=${TRY_IT_OPERATION_ID}`,
    `logs/${TRY_IT_OPERATION_ID}`,
    `resources/apps?app=${BOOKING_APP_ID}&tab=bindings`,
    `usage?group=key&row=${KEYS[0].id}`,
    `keys?key=${KEYS[0].id}`,
    'cli?code=ABCD-EFGH',
];

/** Where a dialog the palette doesn't offer opens: an agent's trigger and memory entry on its page, machines on their
 *  page while the account hasn't asked, cards (drawn in the lab) on theirs. */
const OPENED_AT: Partial<Record<NewKind, { address: string; set?: FixtureSet; lab?: boolean }>> = {
    trigger: { address: `agents/${AGENTS[0].id}` },
    memory: { address: `agents/${AGENTS[0].id}?tab=memory` },
    machines: { address: 'resources/machines', set: 'empty' },
    card: { address: 'resources/cards', lab: true },
};

/** Every New dialog, where its page's button opens it. */
const NEW_DIALOGS = (Object.entries(NEW_IN_CODE) as [NewKind, NewInCodeKind][]).map(([kind, entry]) => {
    const at = OPENED_AT[kind] ?? { address: entry.page! };
    return { kind, entry, set: at.set ?? 'populated', lab: at.lab ?? false, address: `${at.address}${at.address.includes('?') ? '&' : '?'}new=${kind}` };
});

describe('a console acting as a key', { timeout: TEST_S }, () => {
    it.each(ADDRESSES)('asks for nothing only the owner may have at /%s', async (address) => {
        const calls = open(address);
        await calls.settled();
        expect(calls.ownerOnly).toEqual([]);
    });

    it.each(NEW_DIALOGS)('shows the code that makes one at /$address, its guide, and no prompt that needs a setup code', async ({ address, entry, set, lab }) => {
        const calls = open(address, 'key', set as FixtureSet, lab);
        await calls.settled();
        expect(calls.ownerOnly).toEqual([]);
        const dialog = screen.getByRole('dialog', { name: entry.title });
        expect(within(dialog).getByRole('region', { name: 'Create it from your code' }).textContent).toContain('import noclick');
        expect(within(dialog).getByRole('link', { name: /guide/ }).getAttribute('href')).toBe(`https://noclick.com/docs/${entry.guide}`);
        expect(within(dialog).queryByRole('button', { name: 'Copy prompt' })).toBeNull();
    });

    it('would be caught asking: the owner’s console does make those calls, and a key is refused them', async () => {
        const owner = open('keys', 'owner');
        await owner.settled();
        expect(owner.ownerOnly).toContain('GET /v1/keys');
        cleanup();

        const refused = await makeFixtureFetch({ set: 'populated', actsAs: 'key' })(`${DEFAULT_BASE_URL}/v1/keys`, { method: 'GET' });
        expect(refused.status).toBe(403);
        expect((await refused.json()).error.type).toBe('permission_denied');
        for (const operation of OWNER_ONLY_OPERATIONS) {
            const [method, path] = operation.split(' ');
            const sent = path.replace(/\{[^}]+\}/g, 'x');
            const answer = await makeFixtureFetch({ set: 'populated', actsAs: 'key' })(`${DEFAULT_BASE_URL}${sent}`, { method, body: method === 'GET' || method === 'DELETE' ? undefined : '{}' });
            expect(`${operation}: ${answer.status}`).toBe(`${operation}: 403`);
        }
    });

    it('lists no section only the owner opens, and at its address says why with a link to do it on NoClick', async () => {
        const calls = open(`keys?key=${KEYS[0].id}`);
        await calls.settled();
        const nav = screen.getByRole('navigation', { name: 'Developer console' });
        expect(nav.textContent).toContain('Usage');
        expect(nav.textContent).not.toContain('API keys');
        // API keys and the connected apps are both on that page of NoClick's console: a line and a link for each.
        for (const [what, link] of [
            ['keys', 'Manage API keys on NoClick'],
            ['connectedApps', 'See connected apps on NoClick'],
        ] as const) {
            expect(screen.getByText(ownerOnlyWhy(what))).toBeTruthy();
            const anchor = screen.getByRole('link', { name: link });
            expect(anchor.getAttribute('href')).toBe(`https://noclick.com/dashboard/developers/keys?key=${KEYS[0].id}`);
            expect(anchor.getAttribute('target')).toBe('_blank');
        }
        expect(calls.made).not.toContain('GET /v1/keys');
    });

    it('sends a command line’s sign-in to NoClick with its code', async () => {
        const calls = open('cli?code=ABCD-EFGH');
        await calls.settled();
        expect(screen.getByText(ownerOnlyWhy('cliSignIn'))).toBeTruthy();
        const anchor = screen.getByRole('link', { name: 'Approve it on NoClick' });
        expect(anchor.getAttribute('href')).toBe('https://noclick.com/dashboard/developers/cli?code=ABCD-EFGH');
        expect(anchor.getAttribute('target')).toBe('_blank');
    });

    it('shows the code that asks for machines where the request stands, and asks nothing itself', async () => {
        // An account that hasn't asked yet: its code asks, with a key that names machines:vetting.
        const calls = open('resources/machines', 'key', 'empty');
        await calls.settled();
        fireEvent.click(await screen.findByRole('button', { name: 'Ask for machines' }));
        const dialog = await screen.findByRole('dialog', { name: 'Ask for machines' });
        expect(within(dialog).getByRole('region', { name: 'Create it from your code' }).textContent).toContain('accepted_by=');
        expect(calls.made).not.toContain('POST /v1/machines/vetting');
    });

    it('reveals no card’s number, and says why where the owner’s reveal is (cards are drawn in the lab)', async () => {
        const calls = open(`resources/cards?card=${CARDS[0].id}`, 'key', 'populated', true);
        await calls.settled();
        expect(await screen.findByText(ownerOnlyWhy('cardReveal'))).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Reveal details' })).toBeNull();
        cleanup();

        const owner = open(`resources/cards?card=${CARDS[0].id}`, 'owner', 'populated', true);
        await owner.settled();
        expect(await screen.findByRole('button', { name: 'Reveal details' })).toBeTruthy();
    });

    it('offers no prompt that needs a setup code and no key to make, and still shows the steps', async () => {
        const calls = open('quickstart');
        await calls.settled();
        expect(await screen.findByText('Set it up')).toBeTruthy();
        expect(screen.queryByText('Copy prompt')).toBeNull();
        expect(screen.queryByRole('button', { name: /create key/i })).toBeNull();
    });

    it('looks nothing up by id from the palette', async () => {
        const calls = open('');
        await calls.settled();
        act(() => openConsolePalette());
        const search = await screen.findByPlaceholderText('Go to a section');
        fireEvent.change(search, { target: { value: AGENTS[0].id } });
        await new Promise((done) => setTimeout(done, 500));
        expect(calls.made.filter((call) => call.startsWith('GET /v1/objects/'))).toEqual([]);
    });

    it('opens a page’s New dialog from the palette when asked for, and leads with places otherwise', async () => {
        const calls = open('');
        await calls.settled();
        act(() => openConsolePalette());
        const search = await screen.findByPlaceholderText('Go to a section');
        fireEvent.change(search, { target: { value: 'us' } });
        expect(screen.getAllByRole('option')[0].textContent).not.toContain('New user');
        fireEvent.change(search, { target: { value: 'new inbox' } });
        expect(screen.getAllByRole('option')[0].textContent).toContain('New inbox');
        fireEvent.keyDown(search, { key: 'Enter' });
        expect(await screen.findByRole('dialog', { name: 'New inbox' })).toBeTruthy();
    });

    it('names something the console does for every row of what only the owner can do', () => {
        for (const row of Object.values(OWNER_ONLY) as OwnerOnlyRow[]) {
            // A row with no operation is something the API doesn't offer at all, and says so.
            expect(row.operations.length > 0, row.what).toBe(!row.appOnly);
            for (const operation of row.operations) expect(operation).toMatch(/^(GET|POST|PATCH|PUT|DELETE) \/v1\/[a-z_]+(\/(\{[a-z_]+\}|[a-z_]+))*$/);
        }
        expect(new Set(OWNER_ONLY_OPERATIONS).size).toBe(OWNER_ONLY_OPERATIONS.length);
    });
});

describe('the owner’s console', { timeout: TEST_S }, () => {
    it('still has what a key’s leaves out', async () => {
        const calls = open('quickstart', 'owner');
        await calls.settled();
        expect(screen.getByRole('navigation', { name: 'Developer console' }).textContent).toContain('API keys');
        expect(await screen.findByText('Copy prompt')).toBeTruthy();
    });

    it('copies a prompt that has a coding agent make what the dialog makes, as the user the list shows', async () => {
        // The clipboard takes the prompt as the promise the click hands it (Safari's rule), and writes it once its code is made.
        const copied: string[] = [];
        vi.stubGlobal('ClipboardItem', class {
            constructor(readonly items: Record<string, Promise<Blob>>) {}
        });
        const write = vi.spyOn(navigator.clipboard, 'write').mockImplementation(async ([item]) => {
            copied.push(await (await (item as unknown as { items: Record<string, Promise<Blob>> }).items['text/plain']).text());
        });
        onTestFinished(() => {
            write.mockRestore();
            vi.unstubAllGlobals();
        });
        const calls = open('resources/inboxes?user=acme&new=inbox', 'owner');
        await calls.settled();
        const dialog = screen.getByRole('dialog', { name: 'New inbox' });
        // The code makes it for that user too.
        expect(within(dialog).getByRole('region', { name: 'Create it from your code' }).textContent).toContain('user="acme"');
        fireEvent.click(within(dialog).getByRole('button', { name: 'Copy prompt' }));
        await waitFor(() => expect(copied).toHaveLength(1));
        const [prompt] = copied;
        expect(calls.made).toContain('POST /v1/cli/setup_codes');
        expect(prompt).toContain(`-d code=${LAB_SETUP_CODE} >> .env`);
        expect(prompt).toContain(`help me ${NEW_IN_CODE.inbox.goal}.`);
        expect(prompt).toContain(`3. ${NEW_IN_CODE.inbox.ask} Make it as my user "acme"`);
        expect(prompt).toContain(`/docs/${NEW_IN_CODE.inbox.guide}.`);
        expect(await within(dialog).findByText(/^Copied\./)).toBeTruthy();
    });
});
