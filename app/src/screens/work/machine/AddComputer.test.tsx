// @vitest-environment happy-dom
// Add your computer says what agents may do there in one sentence above the steps: three quarters of it, asking before
// running apps or test databases, until you say. Change slides to the settings: the share slider (saved once let go
// on the machine the dialog made, a refusal leaving it where it was, so the computer pairs or a Mac's VM is made at
// it) and Ask first / Yes / No for apps, saved as picked. Done slides back, and the sentence says what was picked,
// with how many agents work at once there once it's online.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { fakeWork } from '../agents/fixtures/workAgents';
import { WorkProviders } from '../agents/fixtures/providers';
import { createWorkLive } from '@/sdk/live';
import { AddComputer } from './AddComputer';

afterEach(cleanup);

function open() {
    const fake = fakeWork();
    const live = createWorkLive();
    render(
        <WorkProviders client={fake.client} live={live}>
            <AddComputer use={{ label: 'Use it', onUse: () => undefined }} onClose={() => undefined} />
        </WorkProviders>
    );
    return { fake, live };
}

const sentence = () => screen.getByTestId('choices-sentence').textContent;
const own = (fake: ReturnType<typeof fakeWork>) => fake.machines.find((m) => m.id === 'm-own-1')!;
const patches = (fake: ReturnType<typeof fakeWork>) => fake.requests.filter((r) => r.method === 'PATCH');
const apps = () => within(screen.getByRole('radiogroup', { name: 'Let agents run apps and test databases on this computer' }));

async function change() {
    await waitFor(() => expect(screen.getByRole('button', { name: 'Change' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Change' }));
    expect(screen.getByText('What agents may do here')).toBeTruthy();
}

it('says the defaults in one sentence above the steps, and adds the computer asking first', async () => {
    const { fake } = open();
    await waitFor(() => expect(screen.getByTestId('install-command').textContent).toContain('--code nc_mach_test'));
    expect(sentence()).toBe('Agents may use three quarters of it, and ask before running apps or test databases.');
    expect(screen.queryByRole('slider')).toBeNull();
    expect(fake.requests.find((r) => r.method === 'POST' && r.path === '/v1/machines/own')!.body).toEqual({ app_testing: 'ask_first' });
    expect(own(fake).app_testing).toBe('ask_first');
});

it('Unattended gives each system’s command with --yes, saying where it’s for', async () => {
    open();
    await waitFor(() => expect(screen.getByTestId('install-command').textContent).toContain('--code nc_mach_test'));
    const command = () => screen.getByTestId('install-command').textContent!;
    expect(command()).toMatch(/\| sudo sh -s -- --code nc_mach_test\S*$/);
    expect(screen.queryByText(/goes ahead without asking/)).toBeNull();
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'How it runs' })).getByRole('radio', { name: 'Unattended' }));
    expect(command()).toMatch(/\| sudo sh -s -- --code nc_mach_test\S* --yes$/);
    expect(screen.getByText(/with --yes it goes ahead without asking/)).toBeTruthy();
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Its system' })).getByRole('radio', { name: 'Mac' }));
    expect(command()).toMatch(/\| sh -s -- --code nc_mach_test\S* --yes$/);
});

it('Change slides to the share and the apps choice, each saved as picked, and Done says them back', async () => {
    const { fake } = open();
    await change();
    expect(apps().getByRole('radio', { name: 'Ask first' }).getAttribute('aria-checked')).toBe('true');
    fireEvent.click(apps().getByRole('radio', { name: 'Yes' }));
    expect(apps().getByRole('radio', { name: 'Yes' }).getAttribute('aria-checked')).toBe('true');
    await waitFor(() => expect(own(fake).app_testing).toBe('by_itself'));
    expect(patches(fake).map((p) => p.body)).toEqual([{ app_testing: 'by_itself' }]);

    const share = screen.getByRole('slider', { name: 'What NoClick uses' });
    share.focus();
    fireEvent.keyDown(share, { key: 'End' });
    await waitFor(() => expect(own(fake).agent_share).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(sentence()).toBe('Agents may use all of it, and can run apps and test databases.'));
    expect(screen.getByTestId('install-command')).toBeTruthy();
    // The way back at the page's top goes there too.
    fireEvent.click(screen.getByRole('button', { name: 'Change' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add your computer' }));
    expect(screen.getByTestId('choices-sentence')).toBeTruthy();
});

it('a refused apps choice goes back to what it was and says why', async () => {
    const { fake } = open();
    await change();
    fake.failNext('PATCH', '/v1/machines/m-own-1', 400, 'Not now.');
    fireEvent.click(apps().getByRole('radio', { name: 'No' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Not now.'));
    expect(apps().getByRole('radio', { name: 'Ask first' }).getAttribute('aria-checked')).toBe('true');
    expect(own(fake).app_testing).toBe('ask_first');
});

it('online, the sentence says how many agents work there at once, and a Mac’s share is locked', async () => {
    const { fake, live } = open();
    await waitFor(() => expect(screen.getByTestId('install-command')).toBeTruthy());
    Object.assign(own(fake), { status: 'running', hostname: 'rowan-mbp', os: 'macOS 15', cpu: 10, memory_gb: 16, conversations_at_once: 6, agent_share_fixed: true });
    act(() => live.deliver('platform:resource', { kind: 'machine', id: 'm-own-1', status: 'running', parent_id: null, version: null }));
    await waitFor(() => expect(sentence()).toBe('Agents may use three quarters of it, up to 6 at once, and ask before running apps or test databases.'));
    fireEvent.click(screen.getByRole('button', { name: 'Change' }));
    expect(screen.getByText('On rowan-mbp.')).toBeTruthy();
    expect(screen.getByRole('slider', { name: 'What NoClick uses' }).getAttribute('aria-disabled')).toBe('true');
});

it('picks what NoClick uses on the slider and saves it on the computer it made, a refusal leaving it where it was', async () => {
    const { fake } = open();
    await waitFor(() => expect(screen.getByTestId('install-command').textContent).toContain('--code nc_mach_test'));
    await change();
    const share = screen.getByRole('slider', { name: 'What NoClick uses' });
    expect(share.getAttribute('aria-valuetext')).toBe('Three quarters');

    // Refused: it says why and goes back to three quarters, with nothing saved.
    fake.failNext('PATCH', '/v1/machines/m-own-1', 400, 'Not now.');
    share.focus();
    fireEvent.keyDown(share, { key: 'Home' });
    expect(share.getAttribute('aria-valuetext')).toBe('A quarter');
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Not now.'));
    expect(share.getAttribute('aria-valuetext')).toBe('Three quarters');
    expect(own(fake).agent_share).toBe(0.75);

    fireEvent.keyDown(share, { key: 'End' });
    expect(share.getAttribute('aria-valuetext')).toBe('All of it');
    await waitFor(() => expect(own(fake).agent_share).toBe(1));
    expect(patches(fake)[1]).toMatchObject({ path: '/v1/machines/m-own-1', body: { agent_share: 1 } });
    expect(screen.queryByRole('alert')).toBeNull();
    await waitFor(() => expect(share.getAttribute('aria-valuenow')).toBe('1'));
});
