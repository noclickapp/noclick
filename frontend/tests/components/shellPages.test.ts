// The shell's pages, in sidebar order: no Needs you page, with Channels second.
import { describe, expect, it } from 'vitest';
import { SHELL_PAGES } from '~/components/shell/pages';
import { GOTO_DESTINATIONS } from '~/lib/shortcuts';

describe('the shell pages', () => {
    it('are Chat, Channels, Automations, Connections, Resources and Settings', () => {
        expect(SHELL_PAGES.map((p) => p.label)).toEqual(['Chat', 'Channels', 'Automations', 'Connections', 'Resources', 'Settings']);
    });

    it('offer no shortcut to a Needs you page', () => {
        expect(GOTO_DESTINATIONS.map((d) => d.label)).not.toContain('Needs you');
    });
});
