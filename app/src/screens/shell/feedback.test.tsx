// @vitest-environment happy-dom
// Sending NoClick feedback from the account menu, as the open app's sidebar has it: the menu's row opens the dialog
// around the account row, which sends the note with its kind through the platform API (a call any of the account's
// keys may make), says it was sent, and on a refusal says the API's own words with its next step.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { NoClick } from 'noclick';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { ClientProvider } from '@/sdk/client';
import { ShellAccount } from './ShellSidebar';

const STATUS = { object: 'status', account: { id: 'acct_7f3a', name: 'Ada Lovelace', email: 'ada@example.test' }, plan: { name: 'member' } };

/** The calls made, and how `POST /v1/feedback` is answered. */
function account(feedback: { status: number; body: unknown }) {
    const sent: { method: string; path: string; body: unknown }[] = [];
    const client = new NoClick({
        apiKey: 'held-by-this-app-server',
        baseUrl: 'http://app.test/api',
        maxRetries: 0,
        fetch: async (input, init) => {
            const path = new URL(String(input)).pathname.replace(/^\/api/, '');
            const method = init?.method ?? 'GET';
            sent.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
            const answer = path === '/v1/feedback' ? feedback : { status: 200, body: STATUS };
            return Response.json(answer.body, { status: answer.status });
        },
    });
    render(
        <ClientProvider client={client}>
            <MemoryRouter>
                <ShellAccount user={{ email: 'ada@example.test', display_name: 'Ada Lovelace' }} collapsed={false} go={() => undefined} />
            </MemoryRouter>
        </ClientProvider>
    );
    return sent;
}

async function openFeedbackFromMenu() {
    const trigger = document.querySelector<HTMLElement>('[data-onboarding="user-menu"]')!;
    act(() => {
        trigger.focus();
        fireEvent.keyDown(trigger, { key: 'Enter' });
    });
    const menu = await screen.findByRole('menu');
    fireEvent.click(within(menu).getByText('Send feedback'));
    return screen.findByRole('dialog', { name: 'Send feedback' });
}

beforeAll(() => {
    Element.prototype.scrollIntoView ??= () => undefined;
});
afterEach(cleanup);

describe('feedback from the account menu', () => {
    it('sends the note with its kind through the platform API, which a key may call, and says it was sent', async () => {
        const sent = account({ status: 201, body: { object: 'feedback', kind: 'bug', received: true } });
        const dialog = await openFeedbackFromMenu();
        const send = within(dialog).getByRole('button', { name: 'Send' }) as HTMLButtonElement;
        expect(send.disabled).toBe(true);
        fireEvent.click(within(dialog).getByRole('radio', { name: 'Bug' }));
        fireEvent.change(within(dialog).getByRole('textbox', { name: 'Your note' }), { target: { value: '  The Work tab forgets my space.  ' } });
        fireEvent.click(send);
        expect(await screen.findByRole('dialog', { name: 'Sent' })).toBeTruthy();
        const note = sent.filter((call) => call.path === '/v1/feedback');
        expect(note).toEqual([{ method: 'POST', path: '/v1/feedback', body: { message: 'The Work tab forgets my space.', kind: 'bug' } }]);
        expect(isOwnerOnly('POST', '/v1/feedback')).toBe(false);
        fireEvent.click(screen.getByRole('button', { name: 'Done' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('says the API’s refusal in its own words, with what to do, and keeps the note', async () => {
        account({
            status: 429,
            body: { error: { type: 'rate_limited', message: 'This account has sent 20 notes today.', next_step: 'Send it tomorrow, or gather the rest into one note.' } },
        });
        const dialog = await openFeedbackFromMenu();
        fireEvent.change(within(dialog).getByRole('textbox', { name: 'Your note' }), { target: { value: 'One more idea.' } });
        fireEvent.click(within(dialog).getByRole('button', { name: 'Send' }));
        const alert = await within(dialog).findByRole('alert');
        expect(alert.textContent).toBe('This account has sent 20 notes today. Send it tomorrow, or gather the rest into one note.');
        expect((within(dialog).getByRole('textbox', { name: 'Your note' }) as HTMLTextAreaElement).value).toBe('One more idea.');
    });

    it('starts a new note each time it opens', async () => {
        account({ status: 201, body: { object: 'feedback', kind: 'general', received: true } });
        let dialog = await openFeedbackFromMenu();
        fireEvent.change(within(dialog).getByRole('textbox', { name: 'Your note' }), { target: { value: 'Half a thought' } });
        fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        dialog = await openFeedbackFromMenu();
        expect((within(dialog).getByRole('textbox', { name: 'Your note' }) as HTMLTextAreaElement).value).toBe('');
        expect(within(dialog).getByRole('radio', { name: 'Feedback' }).getAttribute('aria-checked')).toBe('true');
    });
});
