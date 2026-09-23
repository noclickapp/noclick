// @vitest-environment jsdom
// Approval is a decision on immutable details, not a policy change or editable call.
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { CredentialApproval, type ReviewState } from './CredentialApproval';

afterEach(cleanup);
const state: ReviewState = {
    id: 'request',
    credential_id: 'personal-mail',
    credential_name: 'Personal email',
    node_type: 'automation-gmail',
    operation: 'send_email_message',
    status: 'pending',
    actionable: true,
    consumed: false,
    coordinator: true,
    arguments: {
        to: ['alex@example.test'],
        body: '<script>untrusted()</script>',
    },
};

it('shows the exact recipient and inert content, and submits only the decision', () => {
    const decide = vi.fn();
    const { container } = render(
        <MemoryRouter>
            <CredentialApproval state={state} onDecide={decide} />
        </MemoryRouter>
    );
    expect(screen.getByText('alex@example.test')).toBeTruthy();
    expect(screen.getByText('<script>untrusted()</script>')).toBeTruthy();
    expect(container.querySelector('script, input, textarea')).toBeNull();
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Approve once' }));
    expect(decide).toHaveBeenCalledWith('approved');
    expect(
        screen.getByRole('link', { name: 'Manage rules' }).getAttribute('href')
    ).toBe('/credential/permissions/personal-mail');
});

it('does not offer approval for an expired or previously decided request', () => {
    render(
        <MemoryRouter>
            <CredentialApproval
                state={{ ...state, actionable: false }}
                onDecide={vi.fn()}
            />
        </MemoryRouter>
    );
    expect(screen.queryByRole('button', { name: 'Approve once' })).toBeNull();
    expect(
        screen.getByText(/expired or its connection rules changed/)
    ).toBeTruthy();
});

it('prevents a second click while a decision is being saved', () => {
    const decide = vi.fn();
    render(
        <MemoryRouter>
            <CredentialApproval state={state} saving onDecide={decide} />
        </MemoryRouter>
    );
    fireEvent.click(screen.getByRole('button', { name: 'Approve once' }));
    fireEvent.click(screen.getByRole('button', { name: 'Decline' }));
    expect(decide).not.toHaveBeenCalled();
});
