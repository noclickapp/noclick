// @vitest-environment happy-dom
// Add machine over the fake /v1: one popup with both ways and what each costs, Rent sliding into the machine-buying
// dialog (no agent) whose confirm spells out the month, the day and who runs it, and back again; an account whose
// company NoClick hasn't approved sends it with the rental, which is held (nothing charged) until it's approved; one
// already under review rents without sending it again; your own computer opens Add your computer as it is.
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fakeWork } from '../agents/fixtures/workAgents';
import { WorkProviders } from '../agents/fixtures/providers';
import { AddMachine } from './AddMachine';
import { HOLD_MS } from './BuyMachine';

afterEach(cleanup);

function open(vetting: 'approved' | 'not_submitted' | 'pending' = 'approved') {
    const fake = fakeWork({ vetting });
    const onDone = vi.fn<(id: string | null) => void>();
    render(
        <WorkProviders client={fake.client}>
            <AddMachine onDone={onDone} />
        </WorkProviders>
    );
    return { fake, onDone };
}

const buy = () => screen.getByTestId('buy-machine');
const purchases = (fake: ReturnType<typeof fakeWork>) =>
    fake.requests
        .filter((r) => r.method === 'POST' && r.path === '/v1/machines')
        .map((r) => r.body);

async function toConfirm() {
    fireEvent.click(screen.getByTestId('machine-way-rent'));
    await waitFor(() =>
        expect(within(buy()).getAllByRole('radio').length).toBeGreaterThan(0)
    );
    fireEvent.click(within(buy()).getByRole('radio', { name: /^Small/ }));
    fireEvent.click(
        within(buy()).getByRole('button', { name: 'Choose where' })
    );
    fireEvent.click(within(buy()).getByRole('button', { name: /^Continue/ }));
    await waitFor(() =>
        expect(
            screen.getByRole('heading', { name: 'Rent Small in Europe?' })
        ).toBeTruthy()
    );
}
const unheld = (name: RegExp) =>
    waitFor(
        () =>
            expect(
                within(buy())
                    .getByRole('button', { name })
                    .hasAttribute('disabled')
            ).toBe(false)
    );

describe('the choice', () => {
    it('offers both ways with what each costs, and slides into renting and back', async () => {
        open();
        const choice = screen.getByTestId('add-machine');
        expect(choice.textContent).toContain(
            'Where your agents work. Your account can have both.'
        );
        await waitFor(() =>
            expect(
                screen.getByTestId('machine-way-rent').textContent
            ).toContain('From $8.39 a month')
        );
        expect(screen.getByTestId('machine-way-own').textContent).toContain(
            'Free'
        );
        fireEvent.click(screen.getByTestId('machine-way-rent'));
        expect(
            screen.getByRole('heading', { name: 'Rent a machine' })
        ).toBeTruthy();
        fireEvent.click(
            within(buy()).getByRole('button', { name: 'Add a machine' })
        );
        expect(screen.getByTestId('add-machine')).toBeTruthy();
    });

    it('opens Add your computer for your own', async () => {
        open();
        fireEvent.click(screen.getByTestId('machine-way-own'));
        await waitFor(() =>
            expect(screen.getByTestId('install-command')).toBeTruthy()
        );
    });
});

describe('renting one', () => {
    it('confirms the month, the day and who runs it, then rents it named for where it runs', async () => {
        const { fake } = open();
        await toConfirm();
        const text = buy().textContent ?? '';
        expect(text).toContain('$8.39 a month, $0.28 a day.');
        expect(text).toContain(
            '2 vCPU · 4 GB memory · 40 GB disk · run by Hetzner'
        );
        expect(text).toContain(
            'That’s $0.28 a day, from the day it starts until you delete it. Stopping it doesn’t stop the charge.'
        );
        expect(text).toContain('It starts in about 3 minutes');
        expect(text).toContain('Named europe-box; rename it on its page.');
        await unheld(/^Rent for \$8\.39 a month$/);
        await act(async () =>
            fireEvent.click(
                within(buy()).getByRole('button', { name: /^Rent for/ })
            )
        );
        await waitFor(() => expect(purchases(fake)).toHaveLength(1));
        expect(purchases(fake)[0]).toMatchObject({
            name: 'europe-box',
            size: 'small',
            region: 'eu',
            host: 'hetzner',
            max_monthly_usd: 8.39,
        });
        await waitFor(() =>
            expect(
                screen.getByRole('heading', { name: 'Renting Small in Europe' })
            ).toBeTruthy()
        );
    });

    it('sends the company with the rental when NoClick hasn’t checked it yet, and holds it until it’s approved', async () => {
        const { fake } = open('not_submitted');
        await toConfirm();
        expect(buy().textContent).toContain(
            'NoClick checks your company first'
        );
        expect(buy().textContent).toContain(
            'It starts the moment it’s approved'
        );
        const send = () =>
            within(buy()).getByRole('button', {
                name: 'Send and start when approved',
            });
        await new Promise((r) => setTimeout(r, HOLD_MS + 100));
        // Until the card is filled in, nothing can be sent.
        expect(send().hasAttribute('disabled')).toBe(true);
        const card = screen.getByTestId('vetting-card');
        fireEvent.change(
            within(card).getByRole('textbox', { name: 'Company' }),
            { target: { value: 'Acme Ltd' } }
        );
        fireEvent.change(
            within(card).getByRole('textbox', { name: 'Website' }),
            { target: { value: 'acme.example' } }
        );
        fireEvent.change(
            within(card).getByRole('textbox', { name: 'Registered in' }),
            { target: { value: 'gb' } }
        );
        fireEvent.change(
            within(card).getByRole('textbox', { name: 'What agents do' }),
            { target: { value: 'Answer support email.' } }
        );
        await waitFor(() =>
            expect(send().hasAttribute('disabled')).toBe(false)
        );
        await act(async () => fireEvent.click(send()));
        await waitFor(() =>
            expect(
                screen.getByRole('heading', { name: 'Sent to NoClick' })
            ).toBeTruthy()
        );
        expect(buy().textContent).toContain(
            'europe-box starts once Acme Ltd is approved. Nothing is charged until then.'
        );
        const vetting = fake.requests.filter(
            (r) => r.method === 'POST' && r.path === '/v1/machines/vetting'
        );
        expect(vetting.map((r) => r.body)).toEqual([
            {
                company_name: 'Acme Ltd',
                website: 'acme.example',
                country: 'GB',
                use_case: 'Answer support email.',
                accept_usage_policy: true,
            },
        ]);
        expect(
            fake.machines.find((m) => m.name === 'europe-box')
        ).toMatchObject({
            status: 'awaiting_approval',
            spent_usd_this_month: 0,
        });
    });

    it('rents without sending again while NoClick is already checking the company', async () => {
        const { fake } = open('pending');
        await toConfirm();
        expect(buy().textContent).toContain(
            'NoClick checks Example Commerce first'
        );
        expect(
            within(screen.getByTestId('vetting-card')).queryAllByRole('textbox')
        ).toHaveLength(0);
        await unheld(/^Rent; it starts when approved$/);
        await act(async () =>
            fireEvent.click(
                within(buy()).getByRole('button', { name: /^Rent; it starts/ })
            )
        );
        await waitFor(() =>
            expect(
                screen.getByRole('heading', { name: 'Sent to NoClick' })
            ).toBeTruthy()
        );
        expect(
            fake.requests.filter(
                (r) => r.method === 'POST' && r.path === '/v1/machines/vetting'
            )
        ).toHaveLength(0);
    });
});
