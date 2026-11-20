// Settings → Usage's Person split: each charge is who it was for, as the charge records it (`responsible_user_id`):
// a teammate's run in the account's team workspace, someone who joined one of its workspaces (by their own login,
// though their earlier charges named only their user), and the account's own. A customer of the account's app, no
// person of the account's, keeps its own split.
import { describe, expect, it } from 'vitest';
import { deriveView, dimensionsFor, metered, thingLabel, thingOf, toSnapshot } from './derive';
import type { UsagePageData } from './types';

const ME = 'u-owner';
const SAM = 'u-sam';
const ANA = 'u-ana';
const ANA_USER = 'tenant-ana';
const CUSTOMER = 'tenant-cust';

function group(usd: number, fields: Record<string, unknown>) {
    return {
        current: true,
        day: '2026-10-15',
        created_at: '2026-10-15T09:00:00Z',
        k: JSON.stringify(fields),
        user_id: ME,
        usage_type: 'api_usage',
        usage_subtype: 'exa/search_api',
        unit_type: 'requests',
        user_resource: false,
        n: 1,
        quantity: 1,
        total_cost: usd,
        prompt_tokens: 0,
        completion_tokens: 0,
        ...fields,
    } as unknown as UsagePageData['groups'][number];
}

const snap = toSnapshot({
    now: '2026-10-16T15:20:00Z',
    account: { id: ME },
    period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
    billing: null,
    groups: [
        group(4, { responsible_user_id: ME }),
        group(3, { actual_user_id: SAM, responsible_user_id: SAM }),
        group(2, { pa_tenant_id: ANA_USER, responsible_user_id: ANA }),
        group(1, { pa_tenant_id: ANA_USER }), // before charges named who they were for
        group(0.5, { pa_tenant_id: CUSTOMER, responsible_user_id: ME }),
        group(0.25, {}), // the account's own, before
    ],
    directory: {
        workflows: {},
        agents: {},
        people: {
            [ME]: { name: 'Olu' },
            [SAM]: { name: 'Sam' },
            [ANA]: { name: 'Ana' },
            [ANA_USER]: { name: 'Ana', person: ANA },
            [CUSTOMER]: { name: 'cust@example.com' },
        },
    },
    charges: { rows: [], runs: {}, next: null },
});

describe('who each charge was for', () => {
    it('splits by the person each charge names, one person once', () => {
        const by: Record<string, number> = {};
        for (const row of metered(snap)) {
            const who = thingLabel(snap, 'person', thingOf(snap, row, 'person'));
            by[who] = (by[who] ?? 0) + row.total_cost;
        }
        expect(by).toEqual({ 'Olu (you)': 4.25, Sam: 3, Ana: 3, 'cust@example.com': 0.5 });
        expect(dimensionsFor(deriveView(snap))).toContain('person');
    });
});
