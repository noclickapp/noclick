// @vitest-environment jsdom
// Exercise per-connection lock controls and explicit human saves, including shared
// read-only credentials and the all-actions rule's behavior after revalidation.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import {
    CredentialPermissions,
    type CredentialPolicyState,
} from './CredentialPermissions';

afterEach(cleanup);
const state: CredentialPolicyState = {
    id: 'mail-a',
    name: 'Personal email',
    revision: 0,
    can_edit: true,
    approval_operations: [],
    operations: [
        {
            key: 'gmail.send',
            node_type: 'automation-gmail',
            display_name: 'Send email',
            description: '',
        },
        {
            key: 'gmail.read',
            node_type: 'automation-gmail',
            display_name: 'Read email',
            description: '',
        },
    ],
};
const view = (value = state, onSave = vi.fn()) =>
    render(
        <MemoryRouter>
            <CredentialPermissions state={value} onSave={onSave} />
        </MemoryRouter>
    );

describe('credential approval rules', () => {
    it('saves only the chosen operations, after an explicit human save', () => {
        const save = vi.fn();
        view(state, save);
        fireEvent.click(
            screen.getByRole('button', {
                name: 'Require approval for Send email',
            })
        );
        expect(save).not.toHaveBeenCalled();
        expect(
            screen
                .getByRole('button', {
                    name: 'Require approval for Read email',
                })
                .getAttribute('aria-pressed')
        ).toBe('false');
        fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
        expect(save).toHaveBeenCalledWith(['gmail.send']);
    });

    it('all actions covers future tools without erasing the individual restrictions', () => {
        const save = vi.fn();
        view({ ...state, approval_operations: ['gmail.send'] }, save);
        fireEvent.click(
            screen.getByRole('button', {
                name: 'None',
            })
        );
        expect(
            (
                screen.getByRole('button', {
                    name: 'Require approval for Read email',
                }) as HTMLButtonElement
            ).disabled
        ).toBe(true);
        fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
        expect(save).toHaveBeenCalledWith(['gmail.send', '*']);
    });

    it('does not let shared recipients change the owner’s policy', () => {
        view({
            ...state,
            can_edit: false,
            approval_operations: ['gmail.send'],
        });
        expect(screen.queryByRole('button', { name: 'Save rules' })).toBeNull();
        expect(
            screen
                .getAllByRole('button')
                .every((button) => (button as HTMLButtonElement).disabled)
        ).toBe(true);
    });

    it('keeps rules outside the current search when saving', () => {
        const save = vi.fn();
        view({ ...state, approval_operations: ['gmail.send'] }, save);
        fireEvent.change(
            screen.getByRole('textbox', { name: 'Search tools' }),
            { target: { value: 'Read' } }
        );
        fireEvent.click(
            screen.getByRole('button', {
                name: 'Require approval for Read email',
            })
        );
        fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
        expect(save).toHaveBeenCalledWith(['gmail.send', 'gmail.read']);
    });
});

it('Read-only leaves reads free and locks changes across the whole catalog, even during search', () => {
    const save = vi.fn();
    view({ ...state, approval_operations: ['*', 'retired.action'] }, save);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search tools' }), {
        target: { value: 'Read' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Read-only' }));
    expect(
        screen
            .getByRole('button', { name: 'Require approval for Read email' })
            .getAttribute('aria-pressed')
    ).toBe('false');
    expect(screen.queryByText('Send email')).toBeNull();
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
    expect(save).toHaveBeenCalledWith(['retired.action', 'gmail.send']);
});

it('All explicitly removes restrictions and None covers future actions', () => {
    const save = vi.fn();
    view({ ...state, approval_operations: ['gmail.send'] }, save);
    fireEvent.click(screen.getByRole('button', { name: 'None' }));
    expect(screen.getByText(/including new ones/)).toBeTruthy();
    expect(screen.getAllByText('Approval required')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(screen.getAllByText('Unlocked')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
    expect(save).toHaveBeenCalledWith([]);
});

it('disables shortcuts and locks while saving', () => {
    render(
        <MemoryRouter>
            <CredentialPermissions state={state} saving onSave={vi.fn()} />
        </MemoryRouter>
    );
    expect(
        screen
            .getAllByRole('button')
            .every((button) => (button as HTMLButtonElement).disabled)
    ).toBe(true);
});

it('uses the operation identifier rather than the human title for the read shortcut', () => {
    const save = vi.fn();
    view(
        {
            ...state,
            operations: [
                {
                    ...state.operations[0],
                    display_name: 'Read and forward an email',
                    operation: 'forward_email',
                },
                {
                    ...state.operations[1],
                    display_name: 'Inbox',
                    operation: 'fetch_inbox',
                },
            ],
        },
        save
    );
    fireEvent.click(screen.getByRole('button', { name: 'Read-only' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
    expect(save).toHaveBeenCalledWith(['gmail.send']);
});

it('shows unavailable-connection errors without needing an operation catalog', () => {
    view({ detail: 'Credential not found.' } as CredentialPolicyState);
    expect(screen.getByRole('alert').textContent).toBe('Credential not found.');
    expect(
        screen.queryByRole('group', { name: 'Use without approval' })
    ).toBeNull();
});
