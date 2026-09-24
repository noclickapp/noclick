// Standalone credential approvals belong in the dashboard without a workflow.
// Render the real row in both dashboard sizes to catch null-workflow crashes.
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { AttentionRow } from '~/components/dashboard/sections';
import { nc } from '~/lib/nc';

export default async function () {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    let reviewsOpened = 0;
    try {
        for (const dense of [false, true]) {
            flushSync(() =>
                root.render(
                    createElement(AttentionRow, {
                        item: {
                            id: 'approval:local-review',
                            kind: 'approval',
                            title: 'Review email action',
                            workflow: null,
                            createdAt: '2026-09-24T10:00:00Z',
                            link: '/credential/approval/local-review',
                            meta: { credentialAction: true },
                        },
                        now: '2026-09-24T10:05:00Z',
                        dense,
                        onToggle: () => {
                            reviewsOpened += 1;
                        },
                    })
                )
            );
            nc.assert.truthy(
                host.textContent?.includes('Review email action'),
                'Approval renders without a workflow'
            );
            nc.assert.truthy(
                host.textContent?.includes('5m ago'),
                'Timestamp remains visible'
            );
            if (!dense) {
                const review = [...host.querySelectorAll('button')].find(
                    (button) => button.textContent?.includes('Review action')
                )!;
                flushSync(() => review.click());
                nc.assert.equal(
                    reviewsOpened,
                    1,
                    'Review expands the row instead of opening another tab'
                );
            }
        }
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
