// Settings → Usage by workstream: each charge belongs to the workstream the agent that started its work named, as that
// workstream reads now (one merged into another reads as that one); a drill into one narrows the charges to its groups;
// and a charge reads "for <person> · <workstream>" as far as it says, naming no one where it was the account's own.
import { describe, expect, it } from 'vitest';
import { NOW, fixturePage } from './fixtures';
import { breakdown, chargeQuery, deriveView, dimensionsFor, drillMatch, forLine, lineItem, metered, thingLabel, thingOf, toSnapshot } from './derive';
import type { ChargeRow } from './types';

describe('by workstream', () => {
    const { snap, charges } = fixturePage('team');
    const view = deriveView(snap);

    it('is offered where charges name a workstream, and not where none does', () => {
        expect(dimensionsFor(view)).toContain('workstream');
        expect(dimensionsFor(deriveView(fixturePage('workspace').snap))).not.toContain('workstream');
    });

    it('splits the period by the workstream as it reads now: a merged one’s charges are the one it joined’s', () => {
        const rows = breakdown(view, 'workstream', null);
        expect(rows.map((r) => r.label).sort()).toEqual(['Customer support', 'No workstream named', 'Spring launch']);
        const current = metered(snap).filter((r) => r.current);
        const launch = current.filter((r) => r.metadata.workstream_id === 'ws_launch' || r.metadata.workstream_id === 'ws_prep');
        expect(launch.some((r) => r.metadata.workstream_id === 'ws_prep')).toBe(true);
        const sum = (xs: { total_cost: number }[]) => xs.reduce((a, r) => a + r.total_cost, 0);
        expect(rows.find((r) => r.id === 'ws_launch')!.total).toBeCloseTo(sum(launch), 6);
        expect(rows.reduce((a, r) => a + r.total, 0)).toBeCloseTo(view.spent, 6);
    });

    it('drills into one and narrows the charges to its groups', async () => {
        const match = drillMatch(snap, { path: [{ dim: 'workstream', id: 'ws_launch' }], pick: null })!;
        const { query } = chargeQuery(view, { match });
        expect(query.keys?.length).toBeGreaterThan(0);
        const page = await charges(query, null, 500);
        expect(page.rows.length).toBeGreaterThan(0);
        for (const row of page.rows) expect(['ws_launch', 'ws_prep']).toContain(row.metadata.workstream_id);
    });

    it('a charge says who it was for and its workstream, as far as it says', async () => {
        const page = await charges({ keys: null, day: null }, null, 500);
        const items = page.rows.map((r) => lineItem(snap, r));
        const launch = items.find((i) => i.row.metadata.workstream_id === 'ws_prep')!;
        expect([launch.person, launch.workstream]).toEqual(['Theo Grant', 'Spring launch']);
        expect(forLine(launch)).toBe('for Theo Grant · Spring launch');
        const desk = items.find((i) => i.row.metadata.workflow_id === 'wf_desk' && i.row.metadata.actual_user_id === 'u_sam')!;
        expect(forLine(desk)).toBe('for Sam Ortiz');
        // The account's own work names nobody.
        const own = items.find((i) => i.row.metadata.responsible_user_id === 'u_priya' && !i.row.metadata.workstream_id)!;
        expect([own.person, forLine(own)]).toEqual([null, null]);
        const investor = items.find((i) => i.row.metadata.workflow_id === 'wf_investor' && i.row.metadata.workstream_id);
        if (investor) expect(forLine(investor)).toBe('Spring launch');
    });

    it('labels what names no workstream, and a merged one by the one it joined', () => {
        expect(thingLabel(snap, 'workstream', '__outside__')).toBe('No workstream named');
        const prep = metered(snap).find((r) => r.metadata.workstream_id === 'ws_prep')!;
        expect(thingOf(snap, prep, 'workstream')).toBe('ws_launch');
        expect(thingLabel(snap, 'workstream', 'ws_launch')).toBe('Spring launch');
    });
});

describe('who a charge was for', () => {
    it('names a person by login, never one of the account’s app users, and a workstream only where one was named', () => {
        const snap = toSnapshot({
            now: NOW,
            account: { id: 'u-owner' },
            period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
            billing: null,
            groups: [],
            directory: { workflows: {}, agents: {}, people: { 'u-owner': { name: 'Olu' }, 'u-ana': { name: 'Ana' }, 'tenant-cust': { name: 'cust@example.com' } }, workstreams: { 'ws-1': { name: 'Website' } } },
            charges: { rows: [], runs: {}, next: null },
        });
        const line = (metadata: ChargeRow['metadata']) =>
            lineItem(snap, {
                id: JSON.stringify(metadata),
                created_at: '2026-10-15T09:00:00Z',
                user_id: 'u-owner',
                organization_id: null,
                usage_type: 'api_usage',
                usage_subtype: 'exa/search_api',
                quantity: 1,
                unit_type: 'requests',
                total_cost: 1,
                user_resource: false,
                metadata,
                k: 'k',
            });
        expect(forLine(line({ responsible_user_id: 'u-ana', workstream_id: 'ws-1' }))).toBe('for Ana · Website');
        expect(forLine(line({ responsible_user_id: 'u-owner', platform_api: { tenant_id: 'tenant-cust' } }))).toBeNull();
        expect(forLine(line({ responsible_user_id: 'u-owner', workstream_id: 'ws-1' }))).toBe('Website');
        expect(forLine(line({ responsible_user_id: 'u-gone' }))).toBe('for Former member');
    });
});
