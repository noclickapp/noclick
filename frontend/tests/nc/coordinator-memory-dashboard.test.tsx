// Exercise the real Memories bento and full dashboard drill-down together.
// An isolated transport verifies lazy body reads and preview updates without
// changing the signed-in account's memories.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { BentoDashboard } from '~/components/dashboard/variants';
import {
    CoordinatorMemoriesView,
    MemoriesPreview,
} from '~/components/dashboard/CoordinatorMemories';
import {
    useCoordinatorMemories,
    type MemoryEntry,
    type MemoryTransport,
} from '~/hooks/useCoordinatorMemories';
import type { DashboardData, FocusId } from '~/components/dashboard/types';
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
    const data: DashboardData = {
        workspace: { name: 'Review', kind: 'personal', userName: 'Sam' },
        now: entry.updated_at,
        attention: [],
        runs: { days: [], byWorkflow: [], recent: [] },
        agents: { running: [], turns: [] },
        files: [],
        credentials: [],
        triggers: [],
        upcoming: [],
        notifications: [],
        credits: {
            used: 0,
            cap: 100,
            period: 'month',
            nextRefreshAt: '',
            topup: 0,
            tier: 'free',
            spendByDay: [],
            topSpenders: [],
        },
    };
    function Harness({ enabled = true }: { enabled?: boolean }) {
        const [focus, setFocus] = useState<FocusId | null>(null);
        const memory = useCoordinatorMemories(transport, enabled);
        return (
            <BentoDashboard
                data={data}
                config={{
                    surface: 'hairline',
                    header: 'eyebrow',
                    kpi: 'ledger',
                    layout: 'balanced',
                }}
                focus={focus}
                onFocus={setFocus}
                memories={
                    enabled
                        ? {
                              preview: (
                                  <MemoriesPreview
                                      memory={memory}
                                      now={data.now}
                                      onOpen={(id) => {
                                          setFocus('memories');
                                          if (id) void memory.select(id);
                                      }}
                                  />
                              ),
                              detail: (
                                  <CoordinatorMemoriesView memory={memory} />
                              ),
                          }
                        : undefined
                }
            />
        );
    }
    const host = document.createElement('div');
    host.style.cssText = 'height:900px;width:1200px;position:relative';
    document.body.appendChild(host);
    const root = createRoot(host);
    const click = (element: Element) => flushSync(() => nc.dom.click(element));
    const button = (text: string) =>
        [...host.querySelectorAll('button')].find(
            (el) => el.textContent?.trim() === text
        )!;
    try {
        flushSync(() => root.render(<Harness />));
        await nc.wait.until(
            () => !!host.querySelector('[data-testid="memory-preview-entry"]'),
            3000
        );
        nc.assert.equal(reads, 0, 'The bento reads only headers');
        nc.assert.equal(
            host
                .querySelector('[data-card]:last-child')
                ?.getAttribute('data-card'),
            'memories',
            'Memories is the last bento'
        );
        nc.assert.falsy(
            host.querySelector('[data-testid="coordinator-dock"]'),
            'No floating coordinator'
        );
        click(host.querySelector('[data-testid="memory-preview-entry"]')!);
        await nc.wait.until(
            () =>
                !!host.querySelector('[data-testid="memory-content-preview"]'),
            3000
        );
        nc.assert.equal(reads, 1, 'A preview opens its full memory');
        nc.assert.truthy(
            host.querySelector('[data-testid="dashboard-focus"] h1')
                ?.textContent === 'Memories',
            'Uses the dashboard drill-down'
        );
        nc.assert.falsy(
            host.querySelector('[role="dialog"]'),
            'The detail is a page, not a popup'
        );
        nc.assert.truthy(
            host.querySelector('[data-testid="memory-content-preview"] h2'),
            'Markdown renders as readable content'
        );
        click(button('Edit memory'));
        const description = host.querySelector('[name="memory-description"]')!;
        flushSync(() =>
            nc.dom.type(description, 'Updated release review preferences.')
        );
        click(button('Save memory'));
        await nc.wait.until(
            () =>
                host
                    .querySelector('[data-testid="memory-preview-entry"]')
                    ?.textContent?.includes(
                        'Updated release review preferences.'
                    ) ?? false,
            3000
        );
        click(host.querySelector('[data-testid="dashboard-focus"] button')!);
        nc.assert.falsy(
            host.querySelector('[data-testid="dashboard-focus"]'),
            'Dashboard back closes the drill-down'
        );
        click(host.querySelector('[data-card="memories"] button')!);
        nc.assert.truthy(
            host.querySelector('[data-testid="dashboard-focus"]'),
            'See all opens the full view'
        );
        const before = lists;
        flushSync(() => root.render(<Harness key="gated" enabled={false} />));
        await nc.wait.ms(200);
        nc.assert.falsy(
            host.querySelector('[data-card="memories"]'),
            'Hidden outside the feature rollout'
        );
        nc.assert.equal(lists, before, 'Gated accounts do not fetch memories');
        return { preview: true, fullPage: true, updates: true, gated: true };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
