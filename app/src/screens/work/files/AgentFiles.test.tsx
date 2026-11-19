// @vitest-environment happy-dom
// An agent's one /workspace over the fake /v1 (Wirefern' holds a WhatsApp inbox, its own work and a file you added): the
// real folders with a breadcrumb named for people (the inbox, each chat by its name, what you added), where each file
// came from read from its path alone, the file open as a sheet or beside the list (a phone always a sheet), Upload
// into added/ and Delete asked on the row first.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { WorkProviders } from '../agents/fixtures/providers';
import { fakeWork, id, type FakeWork } from '../agents/fixtures/workAgents';
import { AgentFiles, type AgentFilesProps } from './AgentFiles';
import { chatName, folderLabel, originLine, originOf } from './workspace';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

function show(preview: AgentFilesProps['preview'], { phone = false } = {}) {
    const fake = fakeWork();
    const files = <AgentFiles agentId={id(1)} name="Wirefern" preview={preview} />;
    const view = render(
        <WorkProviders client={fake.client}>{phone ? <PhoneBarSlotProvider slot={null} lead={null} setLeadTaken={() => undefined}>{files}</PhoneBarSlotProvider> : files}</WorkProviders>
    );
    const rows = () => [...view.getByTestId('agent-files').querySelectorAll('[data-file], button')].map((r) => r.textContent ?? '');
    const crumbs = () => [...within(view.getByRole('navigation', { name: 'Folder' })).getAllByText(/.+/)].map((c) => c.textContent);
    const open = async (label: string) => fireEvent.click(await view.findByRole('button', { name: new RegExp(`^${label}`) }));
    return { fake, view, rows, crumbs, open };
}

const written = (fake: FakeWork, method: string) => fake.requests.filter((r) => r.method === method && r.path === `/v1/agents/${id(1)}/workspace/files`).map((r) => r.query.get('path'));

describe('where a file came from, from its path alone', () => {
    it('names a chat from its folder, a group as words and a number with its +', () => {
        expect(chatName('priya-3f9c2a')).toBe('Priya');
        expect(chatName('book-club-07d1e4')).toBe('Book Club');
        expect(chatName('919289199920-3f9c2a')).toBe('+919289199920');
    });

    it('calls the inbox, each chat in it and what you added by name; the rest as named', () => {
        expect(folderLabel('inbox')).toBe('Inbox');
        expect(folderLabel('inbox/bakers-group-07d1e4/')).toBe('Bakers Group');
        expect(folderLabel('added')).toBe('Added by you');
        expect(folderLabel('notes')).toBe('notes');
        expect(folderLabel('notes/added')).toBe('added');
        // An earlier per-chat workspace the cutover kept keeps its inbox.
        expect(folderLabel('earlier/owner/inbox/asha-3f9c2a')).toBe('Asha');
    });

    it('says sent on WhatsApp in its chat, added in NoClick, or made by the agent', () => {
        const line = (path: string) => originLine(originOf(path), 'Wirefern');
        expect(line('inbox/priya-3f9c2a/2026-11-14_2257_photo.jpg')).toBe('Sent on WhatsApp in Priya');
        expect(line('earlier/owner/inbox/asha-3f9c2a/2026-11-01_0900_voice.ogg')).toBe('Sent on WhatsApp in Asha');
        expect(line('added/price-list.pdf')).toBe('Added in NoClick');
        expect(line('made/saturday-orders.xlsx')).toBe('Made by Wirefern');
        // Only a chat's folder in the inbox holds what was sent: anything else there is the agent's.
        expect(line('inbox/notes.md')).toBe('Made by Wirefern');
        expect(line('notes/inbox/x/y.md')).toBe('Made by Wirefern');
        expect(originLine(originOf('inbox/priya-3f9c2a/a.jpg'), 'Wirefern', true)).toBe('Priya');
    });
});

describe('the folder, as it is', () => {
    it('walks its real folders with a breadcrumb named for people', async () => {
        const { rows, crumbs, open } = show('sheet');
        await waitFor(() => expect(rows().map((r) => r.replace(/\d+ files?$/, ''))).toEqual(expect.arrayContaining(['Added by you', 'Inbox', 'made', 'notes'])));
        expect(crumbs()).toEqual(['workspace']);
        await open('Inbox');
        await waitFor(() => expect(crumbs()).toEqual(['workspace', 'Inbox']));
        expect(rows()).toEqual(expect.arrayContaining(['Bakers Group1 file', 'Priya2 files']));
        await open('Priya');
        await waitFor(() => expect(crumbs()).toEqual(['workspace', 'Inbox', 'Priya']));
        expect(screen.getByText('Priya', { selector: '[aria-current]' })).toBeTruthy();
        const photo = screen.getByText('2026-11-10_0957_photo.jpg').closest('[data-file]')!;
        // A row says where it came from (the chat, beside WhatsApp's mark), its size and when.
        expect(photo.textContent).toContain('Priya·1.6 MB');
        // Back up by the breadcrumb.
        fireEvent.click(screen.getByRole('button', { name: 'Inbox' }));
        await waitFor(() => expect(crumbs()).toEqual(['workspace', 'Inbox']));
        fireEvent.click(screen.getByRole('button', { name: 'workspace' }));
        await waitFor(() => expect(crumbs()).toEqual(['workspace']));
    });

    it('opens a file as a sheet with its full path, Download and Copy path', async () => {
        const copied = vi.fn(async () => undefined);
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copied } });
        const { view, open } = show('sheet');
        await open('Inbox');
        await open('Priya');
        expect(view.queryByTestId('agent-file')).toBeNull();
        fireEvent.click(await view.findByRole('button', { name: /^2026-11-10_0957_photo\.jpg/ }));
        const sheet = await screen.findByTestId('agent-file-sheet');
        expect(sheet.textContent).toContain('Sent on WhatsApp in Priya');
        expect(sheet.textContent).toContain('/workspace/inbox/priya-3f9c2a/2026-11-10_0957_photo.jpg');
        const download = within(sheet).getByRole('link', { name: 'Download' });
        expect(download.getAttribute('href')).toBe('https://api.noclick.test/agent/workspace/file?token=inbox%2Fpriya-3f9c2a%2F2026-11-10_0957_photo.jpg&dl=1');
        fireEvent.click(within(sheet).getByRole('button', { name: 'Copy path' }));
        expect(copied).toHaveBeenCalledWith('/workspace/inbox/priya-3f9c2a/2026-11-10_0957_photo.jpg');
    });

    it('keeps the open file beside the list on a wide page, and opens it as a sheet on a phone', async () => {
        const wide = show('beside');
        expect(wide.view.getByTestId('agent-files').dataset.preview).toBe('beside');
        await wide.open('made');
        // The folder's newest file is open beside the list until another is picked; no sheet.
        await waitFor(() => expect(wide.view.getByTestId('agent-file').textContent).toContain('Made by Wirefern'));
        expect(wide.view.getByTestId('agent-file').textContent).toContain('/workspace/made/saturday-orders.xlsx');
        expect(screen.queryByTestId('agent-file-sheet')).toBeNull();
        cleanup();

        const phone = show('beside', { phone: true });
        expect(phone.view.getByTestId('agent-files').dataset.preview).toBe('sheet');
        await phone.open('made');
        expect(phone.view.queryByTestId('agent-file')).toBeNull();
        fireEvent.click(await phone.view.findByRole('button', { name: /^saturday-orders\.xlsx/ }));
        expect((await screen.findByTestId('agent-file-sheet')).textContent).toContain('Made by Wirefern');
    });

    it('uploads into added/ and shows it there', async () => {
        const { fake, view, crumbs } = show('sheet');
        await waitFor(() => expect(view.getByRole('button', { name: 'Upload' }).hasAttribute('disabled')).toBe(false));
        const file = new File(['Open 9-7, closed Mondays.'], 'opening-hours.txt', { type: 'text/plain' });
        await act(async () => {
            fireEvent.change(view.getByTestId('agent-files-upload'), { target: { files: [file] } });
        });
        await waitFor(() => expect(written(fake, 'PUT')).toEqual(['added/opening-hours.txt']));
        expect(fake.requests.find((r) => r.method === 'PUT')!.body).toEqual({ size_bytes: file.size });
        await waitFor(() => expect(crumbs()).toEqual(['workspace', 'Added by you']));
        const row = (await view.findByText('opening-hours.txt')).closest('[data-file]')!;
        expect(row.textContent).toContain('Added in NoClick');
    });

    it('asks on the row before it deletes a file', async () => {
        const { fake, view, open } = show('sheet');
        await open('Added by you');
        const ask = await view.findByRole('button', { name: 'Delete price-list.pdf' });
        fireEvent.click(ask);
        // Kept: nothing is deleted.
        fireEvent.click(view.getByRole('button', { name: 'Keep' }));
        expect(written(fake, 'DELETE')).toEqual([]);
        fireEvent.click(view.getByRole('button', { name: 'Delete price-list.pdf' }));
        fireEvent.click(view.getByRole('button', { name: 'Delete' }));
        await waitFor(() => expect(written(fake, 'DELETE')).toEqual(['added/price-list.pdf']));
        await waitFor(() => expect(view.queryByText('price-list.pdf')).toBeNull());
        expect(fake.workspaces.get(id(1))!.some((f) => f.path === 'added/price-list.pdf')).toBe(false);
    });
});
