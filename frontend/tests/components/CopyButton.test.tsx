// @vitest-environment jsdom
// The shared copy button is an icon button: a circle, named by the app's tooltip, never the browser's.
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { CopyButton } from '~/components/ui/CopyButton';
import { TOOLTIP_SURFACE } from '~/components/shared/ShortcutTooltip';

afterEach(cleanup);

describe('CopyButton', () => {
    it('is a round button named by the app’s tooltip', async () => {
        render(<CopyButton value="curl -fsSL https://example.com/x.sh | sh" />);
        const button = screen.getByRole('button', { name: 'Copy' });
        expect(button.className).toContain('rounded-full');
        expect(button.hasAttribute('title')).toBe(false);
        act(() => button.focus());
        // Radix's tooltip content is itself the role="tooltip" element (since 1.2.13 it no longer renders a
        // hidden second copy for screen readers), so the app's surface is on the element that names it.
        expect((await screen.findByRole('tooltip', { name: 'Copy' })).className).toContain(TOOLTIP_SURFACE);
    });
});
