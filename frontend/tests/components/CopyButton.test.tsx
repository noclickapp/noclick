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
        expect((await screen.findByRole('tooltip', { name: 'Copy' })).parentElement!.className).toContain(TOOLTIP_SURFACE);
    });
});
