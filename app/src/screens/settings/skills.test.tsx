// @vitest-environment happy-dom
// Settings → Skills: each skill's row turns it on or off with the product's switch, which a screen reader names and a
// tap or a key toggles without opening the skill behind the row; one shared with the account is muted for it alone;
// the row itself opens the skill's editor.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { settingsClient, type Observe } from './lab/world';
import { SkillsSection } from './skills';

afterEach(cleanup);

function draw() {
    const sent: { method: string; path: string; body: Record<string, unknown> | null }[] = [];
    const observe: Observe = ({ method, url, body }) => {
        if (method !== 'GET') sent.push({ method, path: url.pathname, body });
    };
    const client = settingsClient({ tier: 'member', balanceUsd: 0, capUsd: null, spentUsd: 0, skills: 'some' }, observe);
    render(
        <ClientProvider client={client}>
            <SkillsSection />
        </ClientProvider>
    );
    return sent;
}

it('turns a skill off with the product’s switch, without opening it', async () => {
    const sent = draw();
    const toggle = await screen.findByRole('switch', { name: 'Disable' });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(toggle);
    await waitFor(() => expect(sent).toEqual([{ method: 'PATCH', path: '/v1/builder_skills/s1', body: { enabled: false } }]));
    fireEvent.keyDown(toggle, { key: 'Enter' });
    expect(screen.queryByLabelText('What it says')).toBeNull();
});

it('mutes one shared with the account for it alone, and reads it as read-only', async () => {
    const sent = draw();
    const mute = await screen.findByRole('switch', { name: 'Mute for me' });
    expect(screen.getByText('Read-only')).toBeTruthy();
    expect(screen.getAllByTitle('Delete')).toHaveLength(2); // the account's own two, not the shared one
    fireEvent.click(mute);
    await waitFor(() => expect(sent).toEqual([{ method: 'PATCH', path: '/v1/builder_skills/s3', body: { muted: true } }]));
    expect(await screen.findByRole('switch', { name: 'Unmute' })).toBeTruthy();
});

it('opens a skill in its editor from the row, and saves its words', async () => {
    const sent = draw();
    fireEvent.click(await screen.findByText('Brand voice'));
    const text = (await screen.findByLabelText('What it says')) as HTMLTextAreaElement;
    await waitFor(() => expect(text.value).toBe('Brand voice: as written.'));
    fireEvent.change(text, { target: { value: 'Short sentences.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(sent).toEqual([{ method: 'PATCH', path: '/v1/builder_skills/s1', body: { name: 'Brand voice', description: 'How we write.', body_text: 'Short sentences.' } }]));
    expect(await screen.findByText('Saved')).toBeTruthy();
});
