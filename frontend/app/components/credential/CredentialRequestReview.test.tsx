// @vitest-environment jsdom
// Grouped reviews must decide only the selected IDs, across connection boundaries.
// Keep ongoing unlocks distinct from single-use grants and render call details inertly.
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import {
    CredentialRequestReview,
    type CallRequest,
    type UnlockRequest,
} from './CredentialRequestReview';

afterEach(cleanup);
const unlocks: UnlockRequest[] = [
    {
        id: 'mail-read',
        credentialId: 'mail',
        credentialName: 'Personal Gmail',
        account: 'personal@example.test',
        kind: 'unlock',
        title: 'Read emails',
        summary: 'Read this inbox.',
        status: 'pending',
    },
    {
        id: 'mail-send',
        credentialId: 'mail',
        credentialName: 'Personal Gmail',
        account: 'personal@example.test',
        kind: 'unlock',
        title: 'Send emails',
        summary: 'Send without asking.',
        status: 'pending',
    },
    {
        id: 'calendar-create',
        credentialId: 'calendar',
        credentialName: 'Work Calendar',
        account: 'work@example.test',
        kind: 'unlock',
        title: 'Create events',
        summary: 'Create meetings.',
        status: 'pending',
    },
];
const calls: CallRequest[] = unlocks.map((item) => ({
    ...item,
    kind: 'call',
    arguments: {
        to: 'alex@example.test',
        body: '<script>untrusted()</script>',
    },
}));
const wrap = (element: React.ReactNode) => (
    <MemoryRouter>{element}</MemoryRouter>
);

it('preselects pending tools without approving them and lets the user exclude a subset', () => {
    const decide = vi.fn();
    render(
        wrap(
            <CredentialRequestReview
                mode="unlock"
                purpose="Help arrange meetings."
                requests={unlocks}
                onDecide={decide}
            />
        )
    );
    expect(
        screen
            .getAllByRole('checkbox', { name: /^Select / })
            .every((el) => el.getAttribute('aria-checked') === 'true')
    ).toBe(true);
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(
        screen.getByRole('checkbox', {
            name: 'Select Send emails on Personal Gmail',
        })
    );
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Unlock 2 tools' }));
    expect(decide).toHaveBeenCalledWith(
        ['mail-read', 'calendar-create'],
        'approved'
    );
    expect(
        screen.getByText('Unselected tools stay locked and pending.')
    ).toBeTruthy();
});

it('shows exact call details and approves once by default without unlocking tools', () => {
    const decide = vi.fn();
    const { container } = render(
        wrap(
            <CredentialRequestReview
                mode="calls"
                purpose="Review these actions."
                requests={calls}
                onDecide={decide}
            />
        )
    );
    expect(
        screen
            .getAllByRole('checkbox', { name: /^Select / })
            .every((el) => el.getAttribute('aria-checked') === 'true')
    ).toBe(true);
    expect(
        screen
            .getByRole('checkbox', { name: 'Don’t ask again for these tools' })
            .getAttribute('aria-checked')
    ).toBe('false');
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    fireEvent.click(
        screen.getByRole('button', {
            name: 'View details for Send emails on Personal Gmail',
        })
    );
    expect(screen.getByText('alex@example.test')).toBeTruthy();
    expect(screen.getByText('<script>untrusted()</script>')).toBeTruthy();
    expect(container.querySelector('script, textarea')).toBeNull();
    expect(
        screen
            .getByRole('checkbox', {
                name: 'Select Send emails on Personal Gmail',
            })
            .getAttribute('aria-checked')
    ).toBe('false');
    fireEvent.click(
        screen.getByRole('checkbox', {
            name: 'Select Send emails on Personal Gmail',
        })
    );
    fireEvent.click(
        screen.getByRole('button', { name: 'Approve 1 call once' })
    );
    expect(decide).toHaveBeenCalledWith(['mail-send'], 'approved');
    expect(screen.queryByRole('button', { name: /Unlock/ })).toBeNull();
    expect(
        screen.getByText('Approve once to keep these tools locked.')
    ).toBeTruthy();
});

it('requires an explicit opt-in to approve and unlock only the selected tools', () => {
    const decide = vi.fn();
    render(
        wrap(
            <CredentialRequestReview
                mode="calls"
                purpose="Review these actions."
                requests={calls}
                onDecide={decide}
            />
        )
    );
    const dontAsk = screen.getByRole('checkbox', {
        name: 'Don’t ask again for these tools',
    });
    fireEvent.click(dontAsk);
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(
        screen.getByRole('checkbox', {
            name: 'Select Send emails on Personal Gmail',
        })
    );
    expect(dontAsk.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(dontAsk);
    fireEvent.click(
        screen.getByRole('button', { name: 'Approve 2 calls & unlock tools' })
    );
    expect(decide).toHaveBeenCalledWith(
        ['mail-read', 'calendar-create'],
        'approved_and_unlocked'
    );
    expect(dontAsk.getAttribute('aria-checked')).toBe('false');
});

it('declining never unlocks tools even when the checkbox was checked', () => {
    const decide = vi.fn();
    render(
        wrap(
            <CredentialRequestReview
                mode="calls"
                purpose="Review these actions."
                requests={calls}
                onDecide={decide}
            />
        )
    );
    fireEvent.click(
        screen.getByRole('checkbox', {
            name: 'Don’t ask again for these tools',
        })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Decline selected' }));
    expect(decide).toHaveBeenCalledWith(
        calls.map((item) => item.id),
        'rejected'
    );
});

it('distinguishes unlocked tools from calls approved once in the result', () => {
    render(
        wrap(
            <CredentialRequestReview
                mode="calls"
                purpose="Review these actions."
                requests={calls.map((item, index) => ({
                    ...item,
                    status: 'approved',
                    toolUnlocked: index === 0,
                }))}
                onDecide={vi.fn()}
            />
        )
    );
    expect(
        screen.getByText('Approved · Tool unlocked for future calls')
    ).toBeTruthy();
    expect(
        screen.getAllByText('Approved once · Tool stays locked')
    ).toHaveLength(2);
    expect(
        screen.queryByText('Your connection rules are unchanged.')
    ).toBeNull();
});

it('removes decided or expired requests from the selection before another submission', () => {
    const decide = vi.fn();
    const view = render(
        wrap(
            <CredentialRequestReview
                mode="calls"
                purpose="Review these actions."
                requests={calls}
                onDecide={decide}
            />
        )
    );
    fireEvent.click(screen.getByRole('button', { name: 'Select all pending' }));
    view.rerender(
        wrap(
            <CredentialRequestReview
                mode="calls"
                purpose="Review these actions."
                requests={calls.map((item, index) => ({
                    ...item,
                    status:
                        index === 0
                            ? 'approved'
                            : index === 1
                              ? 'expired'
                              : 'pending',
                }))}
                onDecide={decide}
            />
        )
    );
    expect(screen.getByText('Approved once · Tool stays locked')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Decline selected' }));
    expect(decide).toHaveBeenCalledWith(['calendar-create'], 'rejected');
});

it('disables decisions while saving and retains the selection when a save fails', () => {
    const decide = vi.fn();
    const view = render(
        wrap(
            <CredentialRequestReview
                mode="unlock"
                purpose="Unlock tools."
                requests={unlocks}
                onDecide={decide}
            />
        )
    );
    fireEvent.click(screen.getByRole('button', { name: 'Select all pending' }));
    view.rerender(
        wrap(
            <CredentialRequestReview
                mode="unlock"
                purpose="Unlock tools."
                requests={unlocks}
                saving
                onDecide={decide}
            />
        )
    );
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' }));
    expect(decide).not.toHaveBeenCalled();
    view.rerender(
        wrap(
            <CredentialRequestReview
                mode="unlock"
                purpose="Unlock tools."
                requests={unlocks}
                error="One connection changed. Review it again."
                onDecide={decide}
            />
        )
    );
    expect(screen.getByRole('alert').textContent).toContain(
        'One connection changed'
    );
    expect(
        screen
            .getAllByRole('checkbox')
            .every((el) => el.getAttribute('aria-checked') === 'true')
    ).toBe(true);
});
