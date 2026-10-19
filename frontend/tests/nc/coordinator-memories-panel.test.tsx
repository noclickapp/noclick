// Exercise the chat's Memories panel: the real side panel over the real memory
// browser. An isolated transport verifies nothing loads until the panel opens,
// the library reads headers only, and an open memory takes the panel's single
// column without changing the signed-in account's memories.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { CoordinatorMemories } from '~/components/dashboard/CoordinatorMemories';
import { SidePanel } from '~/components/shell/SidePanel';
import type { MemoryEntry, MemoryTransport } from '~/hooks/useCoordinatorMemories';
import { nc } from '~/lib/nc';

export default async function () {
    let entry: MemoryEntry = {
        id: '11111111-1111-1111-1111-111111111111',
        name: 'release-preferences',
        description: 'Consult before opening a pull request.',
        content: '## Release checklist\n\nWatch CI until every check finishes.',
        memory_type: 'feedback',
        origin_conversation_id: null,
        version: 1,
        created_at: '2026-09-20T00:00:00Z',
        updated_at: '2026-09-20T00:00:00Z',
    };
    let reads = 0;
    let lists = 0;
    const transport: MemoryTransport = {
        list: async () => {
            lists++;
            const { content: _content, ...header } = entry;
            return { memories: [header], has_more: false };
        },
        get: async () => {
            reads++;
            return { ...entry };
        },
        save: async (input) => {
            entry = { ...entry, ...input, version: entry.version + 1 };
            return entry;
        },
        forget: async () => {},
    };
    let setOpen: (open: boolean) => void = () => {};
    function Harness() {
        const [open, set] = useState(false);
        setOpen = set;
        return (
            <SidePanel open={open} onOpenChange={set} title="Memories">
                <CoordinatorMemories transport={transport} />
            </SidePanel>
        );
    }
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const panel = () => document.querySelector('[role="dialog"] [data-testid="coordinator-memories"]');
    const click = (element: Element) => flushSync(() => nc.dom.click(element));
    const button = (text: string) => [...(panel()?.querySelectorAll('button') ?? [])].find((el) => el.textContent?.trim() === text)!;
    try {
        flushSync(() => root.render(<Harness />));
        await nc.wait.ms(200);
        nc.assert.equal(lists, 0, 'A closed panel fetches nothing');

        flushSync(() => setOpen(true));
        await nc.wait.until(() => !!panel()?.querySelector('[data-testid="memory-entry"]'), 3000);
        nc.assert.equal(reads, 0, 'The library reads only headers');

        click(panel()!.querySelector('[data-testid="memory-entry"]')!);
        await nc.wait.until(() => !!panel()?.querySelector('[data-testid="memory-content-preview"]'), 3000);
        nc.assert.equal(reads, 1, 'Opening a memory reads its body');
        nc.assert.truthy(panel()!.querySelector('[data-testid="memory-content-preview"] h2'), 'Markdown renders as readable content');
        const library = panel()!.querySelector('[aria-label="Memory library"]') as HTMLElement;
        nc.assert.equal(library.offsetParent, null, 'An open memory takes the whole column');

        click(button('Edit memory'));
        flushSync(() => nc.dom.type(panel()!.querySelector('[name="memory-description"]')!, 'Updated release review preferences.'));
        click(button('Save memory'));
        click(button('All memories'));
        await nc.wait.until(
            () => panel()?.querySelector('[data-testid="memory-entry"]')?.textContent?.includes('Updated release review preferences.') ?? false,
            3000
        );

        flushSync(() => setOpen(false));
        await nc.wait.until(() => !panel(), 3000);
        return { lazy: true, singleColumn: true, updates: true };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
