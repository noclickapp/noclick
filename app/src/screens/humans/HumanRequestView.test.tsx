// @vitest-environment happy-dom
// The request page's body: what a person sees and submits, and the console's
// preview of it, which renders the same page contained and never submits.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { answerFromFields, answerSummary, HumanRequestView, type HumanRequestContent } from '@/screens/humans/HumanRequestView';

afterEach(cleanup);

const BRAND = { name: 'Acme Travel', logo_url: null, color: '#1a73e8', support_url: null };
const APPROVE: HumanRequestContent = {
    kind: 'approve',
    message: 'Send the weekly summary?',
    options: [],
    details: { To: 'ana@example.com', Nested: { skipped: true } },
    status: 'pending',
    answer: null,
};
const ASK: HumanRequestContent = { ...APPROVE, kind: 'ask', message: 'Which plan?', options: ['Basic', 'Pro'], details: {} };

describe('HumanRequestView', () => {
    it('submits an approval with its note, and a chosen option', () => {
        const onAnswer = vi.fn();
        render(<HumanRequestView request={APPROVE} brand={BRAND} onAnswer={onAnswer} />);
        expect(screen.getByText('Approval request')).toBeTruthy();
        expect(screen.getByText('ana@example.com')).toBeTruthy();
        expect(screen.queryByText('Nested')).toBeNull();
        fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'ok' } });
        fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
        expect(onAnswer).toHaveBeenLastCalledWith({ choice: undefined, text: 'ok', decision: 'approve' });
        cleanup();
        render(<HumanRequestView request={ASK} brand={BRAND} onAnswer={onAnswer} />);
        const send = screen.getByRole('button', { name: 'Send answer' }) as HTMLButtonElement;
        expect(send.disabled).toBe(true);
        fireEvent.click(screen.getByRole('radio', { name: 'Pro' }));
        fireEvent.click(send);
        expect(onAnswer).toHaveBeenLastCalledWith({ choice: 'Pro', text: '', decision: undefined });
    });

    it('takes an answer in words in place of the options', () => {
        const onAnswer = vi.fn();
        render(<HumanRequestView request={ASK} brand={BRAND} onAnswer={onAnswer} />);
        const send = screen.getByRole('button', { name: 'Send answer' }) as HTMLButtonElement;
        fireEvent.change(screen.getByLabelText('Or answer in your own words'), { target: { value: 'Enterprise, for the team' } });
        expect(send.disabled).toBe(false);
        // No option picked, none is required of the form.
        expect(screen.getAllByRole('radio').every((radio) => !(radio as HTMLInputElement).required)).toBe(true);
        fireEvent.click(send);
        expect(onAnswer).toHaveBeenLastCalledWith({ choice: undefined, text: 'Enterprise, for the team', decision: undefined });
    });

    it('takes several of a question of several, in the order it offers them', () => {
        const onAnswer = vi.fn();
        render(<HumanRequestView request={{ ...ASK, options: ['Mon', 'Tue', 'Wed'], multiple: true }} brand={BRAND} onAnswer={onAnswer} />);
        expect(screen.getByText('Choose any that apply.')).toBeTruthy();
        expect(screen.queryByRole('radio')).toBeNull();
        const send = screen.getByRole('button', { name: 'Send answer' }) as HTMLButtonElement;
        expect(send.disabled).toBe(true);
        // No box is required of the form: none, or any, of them answers it beside words.
        expect(screen.getAllByRole('checkbox').every((box) => !(box as HTMLInputElement).required)).toBe(true);
        fireEvent.click(screen.getByRole('checkbox', { name: 'Wed' }));
        fireEvent.click(screen.getByRole('checkbox', { name: 'Mon' }));
        fireEvent.click(screen.getByRole('checkbox', { name: 'Tue' }));
        fireEvent.click(screen.getByRole('checkbox', { name: 'Tue' }));
        expect(screen.getByLabelText('Note')).toBeTruthy();
        fireEvent.click(send);
        expect(onAnswer).toHaveBeenLastCalledWith({ choices: ['Mon', 'Wed'], text: '', decision: undefined });
        expect(answerFromFields({ choices: ['Mon', 'Wed'], text: ' ' })).toEqual({ choices: ['Mon', 'Wed'] });
        expect(answerSummary({ choices: ['Mon', 'Wed'], text: 'mornings' })).toBe('Mon, Wed — mornings');
    });

    it('in preview is contained and never submits', () => {
        const onAnswer = vi.fn();
        const { container } = render(<HumanRequestView request={APPROVE} brand={BRAND} preview onAnswer={onAnswer} />);
        expect(container.innerHTML).not.toContain('min-h-dvh');
        fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
        expect(onAnswer).not.toHaveBeenCalled();
        cleanup();
        const page = render(<HumanRequestView request={APPROVE} brand={BRAND} onAnswer={onAnswer} />);
        expect(page.container.innerHTML).toContain('min-h-dvh');
    });

    it('shows the closed states instead of a form', () => {
        render(<HumanRequestView request={{ ...APPROVE, status: 'answered', answer: { approved: false, text: 'Not now' } }} brand={BRAND} />);
        expect(screen.getByText('Thanks, your answer was sent')).toBeTruthy();
        expect(screen.getByText('You declined this. Not now')).toBeTruthy();
        expect(screen.queryByRole('button')).toBeNull();
        cleanup();
        render(<HumanRequestView request={{ ...ASK, status: 'expired' }} brand={BRAND} />);
        expect(screen.getByText('This request has expired')).toBeTruthy();
    });

    it("shows an approval's arguments as a table of their own", () => {
        const details = { Action: 'Stripe: Create Refund (stripe.create_refund)', Arguments: { charge: 'ch_1', amount: 25000 } };
        render(<HumanRequestView request={{ ...APPROVE, details }} brand={BRAND} />);
        expect(screen.getByText('Stripe: Create Refund (stripe.create_refund)')).toBeTruthy();
        const args = screen.getByLabelText('Arguments');
        expect(args.textContent).toContain('charge');
        expect(screen.getByText('amount').nextElementSibling?.textContent).toBe('25000');
    });

    it('takes over a handed-off conversation: the transcript, a reply, and Hand back', () => {
        const onReply = vi.fn();
        const onHandBack = vi.fn();
        const handOff: HumanRequestContent = {
            kind: 'hand_off', message: 'Ada wants a manager.', options: [], details: {}, status: 'pending', answer: null,
            handoff: {
                status: 'active', agent: 'support', summary: 'Ada wants a manager about a double charge.', returned_at: null,
                transcript: [
                    { role: 'user', text: 'I was charged twice', created_at: null },
                    { role: 'assistant', text: 'A manager will reply here.', created_at: null },
                    { role: 'person', text: 'Hi Ada, refunding now.', created_at: null },
                ],
            },
        };
        render(<HumanRequestView request={handOff} brand={BRAND} onReply={onReply} onHandBack={onHandBack} />);
        expect(screen.getByText('Conversation')).toBeTruthy();
        expect(screen.getByText('support handed this conversation to you')).toBeTruthy();
        expect(screen.getByText('Ada wants a manager about a double charge.')).toBeTruthy();
        const transcript = screen.getByLabelText('Conversation');
        expect([...transcript.querySelectorAll('li')].map((li) => li.firstChild?.textContent)).toEqual(['Them', 'support', 'You']);
        fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: 'Done, Ada.' } });
        fireEvent.click(screen.getByRole('button', { name: 'Send reply' }));
        expect(onReply).toHaveBeenCalledWith('Done, Ada.');
        fireEvent.click(screen.getByRole('button', { name: 'Hand back to support' }));
        expect(onHandBack).toHaveBeenCalled();
        cleanup();
        const returned = { ...handOff, status: 'answered' as const, handoff: { ...handOff.handoff!, status: 'returned' as const } };
        render(<HumanRequestView request={returned} brand={BRAND} onReply={onReply} />);
        expect(screen.getByText('Handed back to support')).toBeTruthy();
        expect(screen.queryByLabelText('Your reply')).toBeNull();
        expect(screen.queryByRole('button')).toBeNull();
        cleanup();
        // An email thread's replies go to its correspondent, and the page says so.
        expect(screen.queryByText(/emailed to/)).toBeNull();
        render(<HumanRequestView request={{ ...handOff, handoff: { ...handOff.handoff!, emailed_to: 'ada@customer.example' } }}
                                 brand={BRAND} onReply={onReply} />);
        expect(screen.getByText('Your replies are emailed to ada@customer.example.')).toBeTruthy();
    });

    it('maps what was submitted to the answer body', () => {
        expect(answerFromFields({})).toEqual({});
        expect(answerFromFields({ choice: 'Pro', text: '  ' })).toEqual({ choice: 'Pro' });
        expect(answerFromFields({ decision: 'deny', text: 'Too high' })).toEqual({ approved: false, text: 'Too high' });
        expect(answerSummary({ choice: 'Pro', text: 'thanks' })).toBe('Pro — thanks');
        expect(answerSummary({ approved: true }, 'The owner')).toBe('The owner approved this.');
    });
});
