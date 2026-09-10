// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SubscriptionStatusField } from '~/components/workflow/SubscriptionStatusField';

afterEach(cleanup);

describe('SubscriptionStatusField', () => {
    it('renders a healthy registration as plain text with no action', () => {
        render(<SubscriptionStatusField value="Active — listening in the selected channel" action={null} />);
        const status = screen.getByTestId('subscription-status');
        expect(status.textContent).toContain('Active — listening in the selected channel');
        expect(status.dataset.warning).toBeUndefined();
        expect(screen.queryByTestId('subscription-action')).toBeNull();
    });

    it('renders a ⚠ verdict as a warning and drops the glyph', () => {
        render(<SubscriptionStatusField value="⚠ @noclick isn't in #support" action={null} />);
        const status = screen.getByTestId('subscription-status');
        expect(status.dataset.warning).toBe('true');
        expect(status.textContent).toBe("@noclick isn't in #support");
        expect(screen.queryByTestId('subscription-action')).toBeNull();
    });

    it('offers the backend-minted fix and runs its load_value field', async () => {
        let resolve: () => void = () => {};
        const onAction = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
        render(
            <SubscriptionStatusField
                value="⚠ @noclick isn't in #support"
                action={{ field: 'join_channel', label: 'Join #support' }}
                onAction={onAction}
            />
        );
        const button = screen.getByTestId('subscription-action') as HTMLButtonElement;
        expect(button.textContent).toContain('Join #support');
        fireEvent.click(button);
        expect(onAction).toHaveBeenCalledWith('join_channel');
        await waitFor(() => expect(button.disabled).toBe(true));
        fireEvent.click(button); // busy: no second join
        expect(onAction).toHaveBeenCalledTimes(1);
        resolve();
        await waitFor(() => expect(button.disabled).toBe(false));
    });

    it('shows the action only alongside a warning', () => {
        render(
            <SubscriptionStatusField
                value="Active — listening in the selected channel"
                action={{ field: 'join_channel', label: 'Join #x' }}
                onAction={vi.fn()}
            />
        );
        expect(screen.queryByTestId('subscription-action')).toBeNull();
    });

    it('says it is registering while loading with no value yet', () => {
        render(<SubscriptionStatusField value="" isLoading action={null} />);
        expect(screen.getByTestId('subscription-status').textContent).toContain('Registering');
    });
});
