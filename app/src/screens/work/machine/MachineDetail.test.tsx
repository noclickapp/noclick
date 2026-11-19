// @vitest-environment happy-dom
// A machine's own page over the fake /v1: a NoClick machine's header (this month's cost, who's working, how long it's
// been up), its slots and agents, the health verdict with its bars a tap away, a shell in the page and the command
// line for your own terminal, its home folder's files, a resize priced a month and a day, and a delete that says which
// agents move back to their sandboxes. Your own Mac: free, its agents listed, a shell and files in NoClick's VM on it as
// any machine has them, and the three-way app testing choice.
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fakeWork, id, NOW } from '../agents/fixtures/workAgents';
import { WorkProviders } from '../agents/fixtures/providers';
import { ownMac, sampleDisk } from './fixtures/machineWorld';
import { MachineDetail } from './MachineDetail';

afterEach(cleanup);
// xterm.js needs a real browser (the integration test draws it); here the drawer's terminal is a stand-in.
vi.mock('@/ui/terminal/LiveTerminal', () => ({
    LiveTerminal: () => <div data-testid="live-terminal" />,
}));

function open(
    machineId = 'm-ops-box',
    setup: (fake: ReturnType<typeof fakeWork>) => void = () => undefined
) {
    const fake = fakeWork();
    setup(fake);
    const onDeleted = vi.fn();
    render(
        <WorkProviders client={fake.client}>
            <MachineDetail id={machineId} now={NOW} onDeleted={onDeleted} />
        </WorkProviders>
    );
    return { fake, onDeleted };
}

const sent = (
    fake: ReturnType<typeof fakeWork>,
    method: string,
    path: string
) => fake.requests.filter((r) => r.method === method && r.path === path);

describe('a NoClick machine', () => {
    it('leads with this month’s cost, who’s working and how long it’s been up', async () => {
        open();
        await waitFor(() =>
            expect(screen.getByTestId('machine-head').textContent).toContain(
                'ops-box'
            )
        );
        expect(screen.getByTestId('machine-head').textContent).toContain(
            'NoClick machine · Small · US East'
        );
        expect(screen.getByTestId('machine-spend').textContent).toBe(
            '$16.64this month · $31.20 a month'
        );
        expect(screen.getByTestId('machine-working').textContent).toBe(
            '1 of 2agents working now'
        );
        expect(screen.getByTestId('machine-up').textContent).toMatch(
            /^Up 12 dayschecked in/
        );
        // Running plainly: no state line.
        expect(screen.queryByTestId('machine-state')).toBeNull();
        expect(document.body.textContent).not.toMatch(/an hour|us-east/);
    });

    it('shows its slots, then each agent and what it’s doing', async () => {
        open();
        await waitFor(() =>
            expect(screen.getByTestId('machine-slots').textContent).toContain(
                '1 of 2 working now'
            )
        );
        expect(screen.getByText('Infra')).toBeTruthy();
        expect(screen.getByText('Working now')).toBeTruthy();
    });

    it('gives a verdict first, with the three bars a tap away', async () => {
        open();
        await waitFor(() =>
            expect(screen.getByTestId('machine-verdict').textContent).toContain(
                'Plenty of room. Agents aren’t waiting on it.'
            )
        );
        expect(screen.queryByTestId('machine-bars')).toBeNull();
        fireEvent.click(
            within(screen.getByTestId('machine-verdict')).getByRole('button', {
                name: 'Details',
            })
        );
        expect(screen.getByTestId('machine-bars').textContent).toContain(
            '38% busy'
        );
        expect(screen.getByTestId('machine-bars').textContent).toContain(
            '31 of 80 GB used'
        );
    });

    it('opens a shell in the page, and names the command for your own terminal', async () => {
        const { fake } = open();
        fireEvent.click(
            await screen.findByRole('button', { name: /Open a shell/ })
        );
        await waitFor(() =>
            expect(
                sent(fake, 'POST', '/v1/machines/m-ops-box/shell')
            ).toHaveLength(1)
        );
        await waitFor(() =>
            expect(screen.getByTestId('live-terminal')).toBeTruthy()
        );
        expect(screen.getByTestId('shell-drawer').textContent).toContain(
            'Your shell on ops-box'
        );
        expect(
            screen.getByText(/It closes after 15 minutes with nothing typed/)
        ).toBeTruthy();
        fireEvent.click(
            screen.getByRole('button', { name: /From your own computer/ })
        );
        expect(screen.getByTestId('machine-ssh').textContent).toContain(
            'noclick machines ssh ops-box'
        );
        expect(screen.getByTestId('machine-ssh').textContent).toContain(
            "pip install 'noclick[cli]'"
        );
    });

    it('lists its home folder, opens a folder and previews a file', async () => {
        open();
        const files = await screen.findByTestId('machine-files');
        await waitFor(() =>
            expect(
                within(files).getByRole('button', { name: /notes\.txt/ })
            ).toBeTruthy()
        );
        // Folders first, then files by name.
        const rows = within(files)
            .getAllByRole('button')
            .map((b) => b.textContent ?? '');
        expect(
            rows
                .filter((t) => /^(apps|logs|notes\.txt)/.test(t))
                .map((t) => t.replace(/\d.*$/, ''))
        ).toEqual(['apps', 'logs', 'notes.txt']);
        // Above home isn't the machine user's to open.
        expect(
            within(files)
                .getByRole('button', { name: 'home' })
                .hasAttribute('disabled')
        ).toBe(true);
        fireEvent.click(
            within(files).getByRole('button', { name: /notes\.txt/ })
        );
        await waitFor(() =>
            expect(screen.getByTestId('machine-preview').textContent).toContain(
                'Restart the test database'
            )
        );
        fireEvent.click(within(files).getByRole('button', { name: /^logs/ }));
        await waitFor(() =>
            expect(
                within(files).getByRole('button', {
                    name: /backup-2026-11-09\.tar\.gz/,
                })
            ).toBeTruthy()
        );
        fireEvent.click(
            within(files).getByRole('button', {
                name: /backup-2026-11-09\.tar\.gz/,
            })
        );
        expect(screen.getByTestId('machine-preview').textContent).toContain(
            'is over the 16 MB a file can be downloaded here'
        );
    });

    it('changes its size from what its host sells, priced a month and a day, raising its ceiling to the price read', async () => {
        const { fake } = open();
        fireEvent.click(await screen.findByRole('button', { name: 'Change' }));
        const dialog = await screen.findByTestId('resize-machine');
        expect(dialog.textContent).toContain(
            'It stays on DigitalOcean in US East.'
        );
        await waitFor(() =>
            expect(within(dialog).getAllByRole('radio').length).toBeGreaterThan(
                1
            )
        );
        fireEvent.click(within(dialog).getByRole('radio', { name: /^Medium/ }));
        expect(
            within(dialog).getByRole('radio', { name: /^Medium/ }).textContent
        ).toContain('+$1.04 a day');
        fireEvent.click(
            within(dialog).getByRole('button', {
                name: 'Change to Medium · $62.40 a month',
            })
        );
        await waitFor(() =>
            expect(sent(fake, 'PATCH', '/v1/machines/m-ops-box')).toHaveLength(
                1
            )
        );
        expect(sent(fake, 'PATCH', '/v1/machines/m-ops-box')[0].body).toEqual({
            size: 'medium',
            max_monthly_usd: 62.4,
        });
    });

    it('deletes it saying what goes, and its agents move back to their own sandboxes', async () => {
        const { fake, onDeleted } = open();
        fireEvent.click(await screen.findByRole('button', { name: 'Delete…' }));
        const dialog = await screen.findByTestId('delete-machine');
        expect(dialog.textContent).toContain(
            'Its disk and everything on it: 31 GB of files.'
        );
        expect(dialog.textContent).toContain(
            'Infra moves back to its own cloud sandbox, with its files.'
        );
        expect(dialog.textContent).toContain(
            'The charge stops today. This month comes to $16.64.'
        );
        fireEvent.click(
            within(dialog).getByRole('button', { name: 'Delete ops-box' })
        );
        await waitFor(() => expect(onDeleted).toHaveBeenCalled());
        expect(sent(fake, 'DELETE', '/v1/machines/m-ops-box')).toHaveLength(1);
        expect(fake.agents.find((a) => a.id === id(4))!.machine_id).toBeNull();
    });

    it('says what a stopped machine means, with Start as its one action', async () => {
        const { fake } = open('m-ops-box', (f) =>
            Object.assign(f.machines[0], {
                status: 'stopped',
                status_reason: 'stopped',
            })
        );
        const state = await screen.findByTestId('machine-state');
        expect(state.textContent).toContain('It’s still charged $1.04 a day.');
        fireEvent.click(
            within(state).getByRole('button', { name: 'Start it' })
        );
        await waitFor(() =>
            expect(
                sent(fake, 'POST', '/v1/machines/m-ops-box/start')
            ).toHaveLength(1)
        );
        expect(
            (
                screen.getByRole('button', {
                    name: /Open a shell/,
                }) as HTMLButtonElement
            ).disabled
        ).toBe(true);
    });
});

describe('your own Mac', () => {
    const withMac = (fake: ReturnType<typeof fakeWork>) => {
        fake.machines.push(
            ownMac(NOW, {
                working_count: 1,
                agent_states: [{ agent_id: id(1), working: true }],
            })
        );
        fake.agents[0].machine_id = 'm-own-mbp';
        fake.disks.set('m-own-mbp', sampleDisk(NOW));
    };

    it('is free and lists the agents on it', async () => {
        open('m-own-mbp', withMac);
        await waitFor(() =>
            expect(screen.getByTestId('machine-head').textContent).toContain(
                'Your Mac · macOS 15'
            )
        );
        expect(screen.getByTestId('machine-spend').textContent).toBe(
            'Freeyour own machine'
        );
        expect(await screen.findByText('Wirefern')).toBeTruthy(); // its agents load beside the machine
    });

    it('opens a shell in NoClick’s VM on it, as a NoClick machine does', async () => {
        const { fake } = open('m-own-mbp', withMac);
        expect(
            await screen.findByText(
                'Type commands in NoClick’s VM on your Mac as the noclick user, without sudo.'
            )
        ).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: /Open a shell/ }));
        await waitFor(() =>
            expect(
                sent(fake, 'POST', '/v1/machines/m-own-mbp/shell')
            ).toHaveLength(1)
        );
        await waitFor(() =>
            expect(screen.getByTestId('live-terminal')).toBeTruthy()
        );
        expect(screen.getByTestId('shell-drawer').textContent).toContain(
            'Your shell on rowan-mbp'
        );
        fireEvent.click(
            screen.getByRole('button', { name: /From any terminal/ })
        );
        expect(screen.getByTestId('machine-ssh').textContent).toContain(
            'noclick machines ssh rowan-mbp'
        );
    });

    it('lists the noclick user’s home folder on it and previews a file', async () => {
        open('m-own-mbp', withMac);
        const files = await screen.findByTestId('machine-files');
        await waitFor(() =>
            expect(
                within(files).getByRole('button', { name: /notes\.txt/ })
            ).toBeTruthy()
        );
        fireEvent.click(
            within(files).getByRole('button', { name: /notes\.txt/ })
        );
        await waitFor(() =>
            expect(screen.getByTestId('machine-preview').textContent).toContain(
                'Restart the test database'
            )
        );
        expect(document.body.textContent).toContain(
            'the noclick user’s home folder'
        );
    });

    it('waits for it to come online to open a shell, without offering to start it', async () => {
        open('m-own-mbp', (fake) => {
            withMac(fake);
            Object.assign(fake.machines[fake.machines.length - 1], {
                status: 'offline',
            });
        });
        const button = (await screen.findByRole('button', {
            name: /Open a shell/,
        })) as HTMLButtonElement;
        expect(button.disabled).toBe(true);
        expect(document.body.textContent).toContain(
            'rowan-mbp is offline. A shell opens once it’s online.'
        );
        expect(document.body.textContent).toContain(
            'Its files show here while it’s online.'
        );
    });

    it('offers apps and test databases as Ask first, Yes or No, and saves the pick', async () => {
        const { fake } = open('m-own-mbp', withMac);
        const group = await screen.findByRole('radiogroup', {
            name: 'Let agents run apps and test databases',
        });
        expect(
            within(group)
                .getAllByRole('radio')
                .map((r) => [r.textContent, r.getAttribute('aria-checked')])
        ).toEqual([
            ['Ask first', 'true'],
            ['Yes', 'false'],
            ['No', 'false'],
        ]);
        fireEvent.click(within(group).getByRole('radio', { name: 'Yes' }));
        await waitFor(() =>
            expect(sent(fake, 'PATCH', '/v1/machines/m-own-mbp')).toHaveLength(
                1
            )
        );
        expect(sent(fake, 'PATCH', '/v1/machines/m-own-mbp')[0].body).toEqual({
            app_testing: 'by_itself',
        });
    });
});
