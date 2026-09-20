// Verify the real memory browser and editor with an isolated account transport.
// Run in the nc bridge or Chromium integration suite without touching anyone's
// saved memories, including concurrent-edit conflicts and explicit forgetting.
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { CoordinatorMemories } from '~/components/dashboard/CoordinatorMemories';
import type {
    MemoryEntry,
    MemoryTransport,
} from '~/hooks/useCoordinatorMemories';
import { nc } from '~/lib/nc';

export default async function () {
    const entry: MemoryEntry = {
        id: '11111111-1111-1111-1111-111111111111',
        name: 'release-preferences',
        description:
            'Consult before preparing a release or opening a pull request.',
        content:
            'Detailed body: open ready for review and watch CI through completion.',
        memory_type: 'feedback',
        origin_conversation_id: 'coordinator:browser-test',
        version: 1,
        created_at: '2026-09-20T00:00:00Z',
        updated_at: '2026-09-20T00:00:00Z',
    };
    const stored = new Map([[entry.id, entry]]);
    let reads = 0;
    let writes = 0;
    let deletes = 0;
    const transport: MemoryTransport = {
        list: async (query) => ({
            memories: [...stored.values()]
                .filter((item) =>
                    `${item.name} ${item.description}`.includes(query)
                )
                .map(({ content: _content, ...header }) => header),
            has_more: false,
        }),
        get: async (id) => {
            reads++;
            return { ...stored.get(id)! };
        },
        save: async (input) => {
            const old = input.memory_id
                ? stored.get(input.memory_id)
                : undefined;
            if (old && old.version !== input.expected_version)
                throw new Error('Memory changed. Reload it before editing.');
            const saved = {
                ...entry,
                ...input,
                id: input.memory_id || crypto.randomUUID(),
                version: (old?.version || 0) + 1,
            };
            stored.set(saved.id, saved);
            writes++;
            return saved;
        },
        forget: async (id, version) => {
            nc.assert.equal(
                stored.get(id)?.version,
                version,
                'Deletion uses the version the user reviewed'
            );
            stored.delete(id);
            deletes++;
        },
    };
    const host = document.createElement('div');
    host.style.cssText =
        'max-width:640px;padding:24px;background:hsl(var(--background));margin:20px auto';
    document.body.appendChild(host);
    const root = createRoot(host);
    const button = (text: string) =>
        [...host.querySelectorAll('button')].find(
            (element) => element.textContent?.trim() === text
        )!;
    const input = (name: string) =>
        host.querySelector<HTMLInputElement | HTMLTextAreaElement>(
            `[name="${name}"]`
        )!;
    const click = (element: Element) => flushSync(() => nc.dom.click(element));
    const type = (name: string, value: string) =>
        flushSync(() => nc.dom.type(input(name), value));
    try {
        flushSync(() =>
            root.render(createElement(CoordinatorMemories, { transport }))
        );
        await nc.wait.until(
            () => !!host.querySelector('[data-testid="memory-entry"]'),
            3000
        );
        nc.assert.equal(reads, 0, 'Listing loads no memory bodies');
        nc.assert.falsy(
            host.textContent?.includes('Detailed body'),
            'Full memory is not rendered in the catalog'
        );
        click(host.querySelector('[data-testid="memory-entry"]')!);
        await nc.wait.until(() => !!input('memory-content'), 3000);
        nc.assert.equal(
            input('memory-description').value,
            entry.description,
            'Retrieval description has its own field'
        );
        nc.assert.equal(
            input('memory-content').value,
            entry.content,
            'Opening an entry reads the body'
        );
        type(
            'memory-description',
            'Release approvals and reporting preferences.'
        );
        type('memory-content', 'Watch CI and send me the final review link.');
        click(button('Save memory'));
        await nc.wait.until(
            () => writes === 1 && !!host.textContent?.includes('Memory saved'),
            3000
        );
        nc.assert.equal(
            stored.get(entry.id)?.description,
            'Release approvals and reporting preferences.',
            'Saves semantic summary independently'
        );
        nc.assert.equal(
            stored.get(entry.id)?.content,
            'Watch CI and send me the final review link.',
            'Saves full content'
        );

        // Another turn edits after the editor loaded. A failed save must preserve the draft.
        stored.set(entry.id, {
            ...stored.get(entry.id)!,
            version: 3,
            content: 'A newer user correction.',
        });
        type('memory-content', 'My unsaved local edit');
        click(button('Save memory'));
        await nc.wait.until(() => !!host.querySelector('[role="alert"]'), 3000);
        nc.assert.equal(
            input('memory-content').value,
            'My unsaved local edit',
            'Conflict preserves unsaved input'
        );
        nc.assert.equal(
            stored.get(entry.id)?.content,
            'A newer user correction.',
            'Conflict does not overwrite newer data'
        );
        click(button('Reload saved version'));
        await nc.wait.until(
            () => input('memory-content').value === 'A newer user correction.',
            3000
        );
        type('memory-content', 'Discard this draft');
        click(button('Reload saved version'));
        await nc.wait.until(
            () => input('memory-content').value === 'A newer user correction.',
            3000
        );

        click(host.querySelector('[aria-label="Delete memory"]')!);
        nc.assert.equal(deletes, 0, 'Delete requires an explicit confirmation');
        click(button('Cancel'));
        nc.assert.equal(stored.size, 1, 'Cancelling keeps memory');
        click(host.querySelector('[aria-label="Delete memory"]')!);
        click(button('Forget memory'));
        await nc.wait.until(
            () => !!host.textContent?.includes('No memories yet'),
            3000
        );
        nc.assert.equal(deletes, 1, 'Confirmed deletion persists');
        click(button('Add'));
        type('memory-name', 'report-format');
        type('memory-description', 'Consult when writing my weekly report.');
        type('memory-content', 'Use concise bullets and links to evidence.');
        click(button('Save memory'));
        await nc.wait.until(
            () => writes === 2 && !!host.textContent?.includes('Memory saved'),
            3000
        );
        click(button('All memories'));
        await nc.wait.until(
            () => !!host.querySelector('[data-testid="memory-entry"]'),
            3000
        );
        const search = host.querySelector('[aria-label="Search memories"]')!;
        flushSync(() => nc.dom.type(search, 'no-such-memory'));
        await nc.wait.until(
            () => !!host.textContent?.includes('No matching memories'),
            3000
        );
        flushSync(() => nc.dom.type(search, 'report-format'));
        await nc.wait.until(
            () => !!host.querySelector('[data-testid="memory-entry"]'),
            3000
        );
        return {
            reads,
            writes,
            deletes,
            conflictProtected: true,
            separateDescription: true,
        };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
