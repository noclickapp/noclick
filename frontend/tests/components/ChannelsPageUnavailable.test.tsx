// @vitest-environment jsdom
// Channels with no platform registered (the open edition): the page says
// they aren't available here, and shows no sample conversations.
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { ChannelsPage } from '~/components/shell/ChannelsPage';
import { hasPlatformChannels } from '~/components/shell/channels/platform';

describe('Channels without a platform', () => {
    it('says Channels are not available here, and nothing else', () => {
        expect(hasPlatformChannels()).toBe(false);
        render(
            <MemoryRouter initialEntries={['/dashboard?tab=channels']}>
                <ChannelsPage user={{ email: 'dana@example.com' }} />
            </MemoryRouter>
        );
        expect(screen.getByTestId('channels-unavailable').textContent).toContain("Channels aren't available here");
        expect(screen.queryByTestId('channels-page')).toBeNull();
        expect(screen.queryByRole('textbox')).toBeNull();
    });
});
