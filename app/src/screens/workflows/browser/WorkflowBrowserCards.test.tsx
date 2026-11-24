// @vitest-environment happy-dom
//
// An automation's card draws its steps' marks from the node icon map, which can land after the card first draws: the
// dashboard reached by a client navigation (the landing page's Dashboard link) loads the map as it mounts. The card
// draws again once it's set, so its steps aren't left as blank tiles and its app pill as an empty one.
import { afterEach, describe, expect, it } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { setNodeIconData } from '@/lib/nodeIconRegistry';
import type { SerializedNodeMeta } from '@/lib/nodeCatalogTypes';
import { WorkflowCard } from './WorkflowBrowserCards';
import { mapWorkflowApp } from './workflowBrowserStore';
import { listed } from './fakeBrowserClient';

afterEach(cleanup);

// A listing's `preview` as GET /v1/workflows?include=preview answers it.
const preview = {
    nodes: [
        { id: 'schedule', type: 'trigger-cron', position: { x: 0, y: 0 }, config: {} },
        { id: 'read', type: 'automation-slack', position: { x: 300, y: 0 }, config: { operation: 'get_channel_history' } },
        { id: 'post', type: 'automation-slack', position: { x: 600, y: 0 }, config: { operation: 'send_message' } },
    ],
    edges: [
        { id: 'e1', source: 'schedule', target: 'read' },
        { id: 'e2', source: 'read', target: 'post' },
    ],
};

// Two entries of the dashboard's icon map (/api/node-icons/<version>) as it serves them: an inline mark and a file.
const ICONS = {
    'trigger-cron': {
        type: 'trigger-cron',
        label: 'Schedule',
        iconColor: 'text-foreground',
        iconHtml:
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-clock"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
    },
    'automation-slack': {
        type: 'automation-slack',
        label: 'Slack',
        iconColor: '',
        iconHtml: '<img loading="lazy" decoding="async" src="/icons/slack.svg" alt=""/>',
    },
} as unknown as Record<string, SerializedNodeMeta>;

describe('an automation card', () => {
    it('draws its steps’ marks once the icon map lands after it', () => {
        const workflow = mapWorkflowApp(listed('w1', 'Morning Slack Channel Summary', 'owner', { preview }));
        const noop = () => undefined;
        const { container } = render(
            <WorkflowCard workflow={workflow} isMultiSelected={false} onClick={noop} onSettings={noop} onFork={noop} />
        );
        const slackTiles = () => container.querySelectorAll('svg image[href="/icons/slack.svg"]').length;
        const scheduleTiles = () => container.querySelectorAll('svg foreignObject .lucide-clock').length;
        const pillMarks = () => container.querySelectorAll('img[src="/icons/slack.svg"]').length;
        // Three blank tiles until the map is set.
        expect(container.querySelectorAll('svg rect').length).toBeGreaterThanOrEqual(3);
        expect([slackTiles(), scheduleTiles(), pillMarks()]).toEqual([0, 0, 0]);

        act(() => setNodeIconData(ICONS));

        expect([slackTiles(), scheduleTiles()]).toEqual([2, 1]);
        expect(pillMarks()).toBe(1);
    });
});
