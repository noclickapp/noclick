// Settings → Usage's third level: inside a service's item (a model, a tool, a line), what used it, read from the
// attribution each charge carries; the builder as one of those, never as a model; the drill's steps in the URL; and
// a site's hourly reading as one line of the charges table.
import { describe, expect, it } from 'vitest';
import {
    CHAT,
    EARLIER,
    consumerOf,
    consumers,
    deriveView,
    drillFromParams,
    drillLabels,
    drillList,
    drillMatch,
    drillToParams,
    facets,
    foldReadings,
    lineItem,
    metered,
    thingOf,
    toSnapshot,
    type Drill,
} from '~/components/usage/page/derive';
import type { ChargeRow, UnitType, UsagePageData } from '~/components/usage/page/types';

const ME = 'u-1';
const WF = 'wf-1';
const LUNA = 'openrouter/~openai/gpt-luna-latest';
const OSS = 'openrouter/openai/gpt-oss-120b';
const CHAT_AGENT = 'pa-chat';
const SUPPORT = 'pa-support';
const SITE = 'proj-1';

function group(subtype: string, usd: number, fields: Record<string, unknown> = {}, usageType = 'ai_usage') {
    return {
        current: true,
        day: '2026-10-15',
        created_at: '2026-10-15T09:00:00Z',
        k: `${subtype}|${JSON.stringify(fields)}|${usageType}`,
        user_id: ME,
        usage_type: usageType,
        usage_subtype: subtype,
        unit_type: 'tokens',
        user_resource: false,
        n: 1,
        quantity: 1000,
        total_cost: usd,
        prompt_tokens: 0,
        completion_tokens: 0,
        ...fields,
    } as unknown as UsagePageData['groups'][number];
}

const DATA: UsagePageData = {
    now: '2026-10-16T15:20:00Z',
    account: { id: ME },
    period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
    billing: null,
    groups: [
        group(LUNA, 4, { surface: 'coordinator' }),
        group(LUNA, 3, { pa_agent_id: CHAT_AGENT }),
        group(LUNA, 2, { pa_agent_id: SUPPORT }),
        group(LUNA, 1.5, { workflow_id: WF, node_id: 'agent-1' }),
        group(LUNA, 0.5, { workflow_id: WF }),
        group(LUNA, 0.25),
        group('noclick/builder-1', 5, { workflow_id: WF }, 'ai_builder'),
        group('noclick/testing-1', 0.75, { workflow_id: WF }, 'ai_testing'),
        group('exa/search_api', 0.2, { pa_agent_id: SUPPORT }, 'api_usage'),
        group(OSS, 0.01, { surface: 'workflow_name', workflow_id: WF }),
    ],
    directory: {
        workflows: { [WF]: { name: 'Inbox triage' } },
        agents: { [`${WF}:agent-1`]: { name: 'Support agent' }, [CHAT_AGENT]: { name: 'coordinator', chat: true }, [SUPPORT]: { name: 'Larkspur concierge' } },
        people: { [ME]: { name: 'Ada' } },
        projects: { [SITE]: { name: 'Larkspur Lane Bakery' } },
    },
    charges: { rows: [], runs: {}, next: null },
};

const snap = toSnapshot(DATA);
const view = deriveView(snap);

describe('what used each item', () => {
    it('splits one model by what used it, the coordinator and its agent as one chat', () => {
        const rows = consumers(view, 'ai', LUNA);
        expect(rows.map((r) => [r.label, r.total])).toEqual([
            ['Chat with NoClick', 7],
            ['Larkspur concierge', 2],
            ['Support agent · Inbox triage', 1.5],
            ['Inbox triage (step not recorded)', 0.5],
            ['Earlier (not recorded)', 0.25],
        ]);
        expect(rows[0].id).toBe(CHAT);
        expect(rows[rows.length - 1].id).toBe(EARLIER);
    });

    it('reads the builder and test runs as what used NoClick’s own model, never as models', () => {
        const items = facets(view, 'ai');
        expect(items.map((r) => r.label)).not.toContain('AI Builder');
        const own = items.find((r) => r.label === 'NoClick’s own model');
        expect(own?.total).toBe(5.75);
        expect(consumers(view, 'ai', own!.id).map((r) => r.label)).toEqual(['AI Builder · Inbox triage', 'Test runs · Inbox triage']);
        // Naming an automation is the builder's call too, on a model of its own.
        expect(consumers(view, 'ai', OSS).map((r) => r.label)).toEqual(['AI Builder · Inbox triage']);
    });

    it('names what used a charge wherever the page reads one', () => {
        const byLabel = (subtype: string, fields: Record<string, unknown>) =>
            consumerOf(snap, metered(snap).find((r) => r.usage_subtype === subtype && Object.entries(fields).every(([k, v]) => r.metadata[k as 'workflow_id'] === v))!).label;
        expect(byLabel('exa/search_api', {})).toBe('Larkspur concierge');
        expect(byLabel(LUNA, { surface: 'coordinator' })).toBe('Chat with NoClick');
    });
});

describe('a charge recorded in a platform agent’s own run', () => {
    // A platform agent runs on a workflow of its own, named after it, with one node named after it too. A call its
    // turn made under another key (the coordinator's grant making a site's photo) carries that node and no agent id;
    // the directory names the agent that runs on the node.
    const COORD_WF = 'wf-coordinator';
    const SUPPORT_WF = 'wf-larkspur';
    const GONE_WF = 'wf-scout';
    const IMAGE = 'openai/gpt-image-2.5-sunburst';
    const ran = (workflow: string) => ({ workflow_id: workflow, node_id: 'agent', pa_key_id: 'key-1', pa_surface: 'ai', surface: 'platform_ai_image' });
    const data: UsagePageData = {
        ...DATA,
        groups: [
            group(IMAGE, 0.01, ran(COORD_WF)),
            group(LUNA, 3, { pa_agent_id: CHAT_AGENT, workflow_id: COORD_WF, node_id: 'agent' }),
            group(IMAGE, 0.02, ran(SUPPORT_WF)),
            group(LUNA, 2, { pa_agent_id: SUPPORT, workflow_id: SUPPORT_WF, node_id: 'agent' }),
            group(IMAGE, 0.04, ran(GONE_WF)),
        ],
        directory: {
            ...DATA.directory,
            workflows: { [COORD_WF]: { name: 'coordinator' }, [SUPPORT_WF]: { name: 'Larkspur concierge' }, [GONE_WF]: { name: 'scout' } },
            agents: {
                [CHAT_AGENT]: { name: 'coordinator', chat: true },
                [`${COORD_WF}:agent`]: { name: 'coordinator', chat: true, agent: CHAT_AGENT },
                [SUPPORT]: { name: 'Larkspur concierge' },
                [`${SUPPORT_WF}:agent`]: { name: 'Larkspur concierge', agent: SUPPORT },
                // An agent since deleted: only its node's label is left, the same as its automation's name.
                [`${GONE_WF}:agent`]: { name: 'scout' },
            },
        },
    };
    const s = toSnapshot(data);
    const charge = (workflow: string): ChargeRow => ({
        id: `photo-${workflow}`,
        created_at: '2026-10-15T11:35:28Z',
        user_id: ME,
        organization_id: 'org-1',
        usage_type: 'ai_usage',
        usage_subtype: IMAGE,
        quantity: 1,
        unit_type: 'images',
        total_cost: 0.01,
        user_resource: false,
        metadata: { workflow_id: workflow, node_id: 'agent', execution_id: 'run-1', surface: 'platform_ai_image', platform_api: { key_id: 'key-1', surface: 'ai' } },
        k: IMAGE,
    });

    it('reads the coordinator’s site photo as the chat with NoClick, said once', () => {
        const photo = lineItem(s, charge(COORD_WF));
        expect([photo.thing, photo.runner, photo.thingKind]).toEqual(['Chat with NoClick', null, 'chat']);
    });

    it('reads another agent’s as that agent, once, and one thing with what it spent itself', () => {
        expect(lineItem(s, charge(SUPPORT_WF)).thing).toBe('Larkspur concierge');
        expect(consumers(deriveView(s), 'ai', IMAGE).map((r) => r.label)).toEqual(['scout', 'Larkspur concierge', 'Chat with NoClick']);
        const view = deriveView(s);
        expect(consumers(view, 'ai', LUNA).map((r) => [r.label, r.total])).toEqual([
            ['Chat with NoClick', 3],
            ['Larkspur concierge', 2],
        ]);
        // By agent, the photo is the agent that made it.
        expect(thingOf(s, metered(s).find((r) => r.usage_subtype === IMAGE && r.metadata.workflow_id === SUPPORT_WF)!, 'agent')).toBe(SUPPORT);
        expect(thingOf(s, metered(s).find((r) => r.usage_subtype === IMAGE && r.metadata.workflow_id === COORD_WF)!, 'agent')).toBe(CHAT);
    });

    it('names an automation named after its agent once', () => {
        expect(lineItem(s, charge(GONE_WF)).thing).toBe('scout');
    });
});

describe('the drill', () => {
    const drill: Drill = { path: [{ dim: 'service', id: 'ai' }, { dim: 'item', id: LUNA }], pick: CHAT };

    it('goes service › item › what used it, and each level narrows the page', () => {
        expect(drillList({ path: [] }, 'service')).toEqual({ kind: 'dim', dim: 'service' });
        expect(drillList({ path: drill.path.slice(0, 1) }, 'service')).toEqual({ kind: 'facet', service: 'ai' });
        expect(drillList(drill, 'service')).toEqual({ kind: 'consumer', service: 'ai', item: LUNA });
        const total = (d: Drill) => metered(snap).filter(drillMatch(snap, d) ?? (() => true)).reduce((a, r) => a + r.total_cost, 0);
        expect(total({ path: drill.path.slice(0, 1), pick: null })).toBeCloseTo(17.01);
        expect(total({ path: drill.path, pick: null })).toBe(11.25);
        expect(total(drill)).toBe(7);
        expect(drillLabels(view, drill)).toEqual(['AI models', 'GPT-Luna Latest', 'Chat with NoClick']);
    });

    it('rides the URL and comes back as it was', () => {
        const params = drillToParams(drill);
        expect(drillFromParams(params.in, params.pick)).toEqual(drill);
    });
});

describe('a site’s hourly reading', () => {
    // Quantities as the meter records them: traffic in millions of requests, what's kept in release-months and GB-hours.
    const reading = (id: string, subtype: string, usd: number, quantity = 0.0063, unit: UnitType = 'gb_hours', extra = {}): ChargeRow => ({
        id,
        created_at: '2026-10-15T10:00:01Z',
        user_id: ME,
        organization_id: null,
        usage_type: 'api_usage',
        usage_subtype: subtype,
        quantity,
        unit_type: unit,
        total_cost: usd,
        user_resource: false,
        metadata: { project_id: SITE, from: '2026-10-15T09:00:00Z', to: '2026-10-15T10:00:00Z', ...extra },
        k: subtype,
    });

    it('reads as one line for the site, made of its charges', () => {
        const rows = [
            reading('c-1', 'apps/hosting', 0.004, 0.0012, 'million_requests', { requests: 1234 }),
            reading('c-2', 'apps/releases', 0.002, 0.00137, 'month'),
            reading('c-3', 'apps/build_outputs', 0.001, 0.0001),
            reading('c-4', 'apps/build_cache', 0.001),
            { ...reading('c-5', 'apps/build', 0.02, 74, 'seconds'), created_at: '2026-10-15T09:41:00Z', metadata: { project_id: SITE } },
        ];
        const [hour, build] = foldReadings(rows.map((r) => lineItem(snap, r)));
        expect([hour.what, hour.thing, hour.quantity]).toEqual(['Site hosting', 'Larkspur Lane Bakery', 'an hour']);
        expect(hour.usd).toBeCloseTo(0.008);
        expect(hour.parts?.map((p) => [p.what, p.quantity])).toEqual([
            ['Site traffic', '1,234 requests'],
            ['Site versions kept', '1.0 h'],
            ['Site files kept', '105 KB·h'],
            ['Site build cache', '6.5 MB·h'],
        ]);
        expect([build.what, build.parts]).toEqual(['Site build', undefined]);
    });
});
