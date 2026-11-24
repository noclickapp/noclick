// @vitest-environment happy-dom
// A channel's tabs: each channel opens on Messages, and a tab picked the moment another channel is drawn stays picked.
// The pane stays mounted from one channel to the next. Put back on Messages in an effect, the tabs undid a tab clicked
// after the next channel was drawn and before that effect ran, which React leaves for a later task unless something
// in that render makes it run them at once (Work's own channel switches are such a render today; the hook doesn't
// count on it).
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { clickAsDrawn } from '@/lib/clickAsDrawn';
import { WorkProviders } from '../agents/fixtures/providers';
import { fakeWorkAgent } from '../conversation/fixtures/workAgent';
import type { ChannelShelf } from './shelf';
import { ChannelTabBar, useChannelTabs } from './tabs';

afterEach(cleanup);

const nothing = async () => [];
const shelf = { pins: nothing, bookmarks: nothing, files: nothing, links: nothing } as unknown as ChannelShelf;

/** A channel's pane: one pane, the channel it shows changed from outside any event, as a read landing changes it. */
function channelPane() {
    let open: (id: string) => void = () => undefined;
    function Pane() {
        const [channelId, setChannelId] = useState('general');
        open = setChannelId;
        const tabs = useChannelTabs(channelId, shelf);
        return (
            <>
                <h1>#{channelId}</h1>
                <ChannelTabBar tabs={tabs} />
                <p data-testid="view">{tabs.view}</p>
            </>
        );
    }
    render(
        <WorkProviders client={fakeWorkAgent().client}>
            <Pane />
        </WorkProviders>
    );
    return { open: (id: string) => open(id) };
}

const view = () => screen.getByTestId('view').textContent;
const tab = (name: string) => screen.getByRole('tab', { name: new RegExp(`^${name}`) });

it('keeps a tab picked as another channel is drawn', async () => {
    const pane = channelPane();
    fireEvent.click(tab('Bookmarks'));
    expect(view()).toBe('bookmarks');

    const click = clickAsDrawn(() => (screen.queryByRole('heading', { name: '#launch' }) ? tab('Pins') : null));
    pane.open('launch');
    await waitFor(() => expect(click.clicked()).toBe(true));
    await waitFor(() => expect(view()).toBe('pins'));
    expect(tab('Pins').getAttribute('aria-selected')).toBe('true');
});

it('opens another channel on Messages', () => {
    const pane = channelPane();
    fireEvent.click(tab('Files & links'));
    expect(view()).toBe('files');
    act(() => pane.open('launch'));
    expect(screen.getByRole('heading', { name: '#launch' })).toBeTruthy();
    expect(view()).toBe('messages');
});
