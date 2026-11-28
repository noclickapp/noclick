// A machine shared with a space, as its Resources tab reads it: the summary's shared machines, with the agents here
// placed on each; a machine's levels in people's words; and Share offered on the account's machines, never on an
// agent's sandbox.
import { describe, expect, it } from 'vitest';
import { shareable } from './actions';
import { levelWords, ownMachine, thingKey, toSummary, type Thing } from './data';

const summary = toSummary({
    kinds: {
        agents: { count: 1, items: [{ id: 'agt_builder', name: 'builder', state: 'idle' }] },
        machines: {
            count: 1,
            up: 1,
            items: [{ id: 'nc-live-1', kind: 'sandbox', machine_id: null, agent_id: 'agt_builder', state: 'up' }],
            shared: [
                { id: 'lnk_dev', ref: 'mch_dev', name: 'dev-box', kind: 'own', status: 'running', linked: true, members_level: 'use', guests_level: 'none', level: 'use', used_by: ['agt_builder'] },
                { id: 'lnk_ops', ref: 'mch_ops', name: 'ops-box', kind: 'noclick', status: 'stopped', linked: true, members_level: 'run', guests_level: 'none', level: 'use', used_by: [] },
            ],
        },
    },
});

const row = (t: Partial<Thing> & Pick<Thing, 'ref'>): Thing => ({ key: thingKey('machines', t.ref), kind: 'machines', name: t.ref, link: null, usedBy: [], ...t });

describe('a machine shared with a space', () => {
    it('reads the summary’s shared machines beside where its agents run', () => {
        expect(summary.machines.items.map((m) => m.kind)).toEqual(['sandbox']);
        expect(summary.machines.shared.map((m) => [m.ref, m.name, m.own, m.status, m.membersLevel, m.usedBy])).toEqual([
            ['mch_dev', 'dev-box', true, 'running', 'use', ['agt_builder']],
            ['mch_ops', 'ops-box', false, 'stopped', 'run', []],
        ]);
    });

    it('names its levels as people read them', () => {
        expect(['none', 'run', 'use'].map((l) => levelWords('machine', l))).toEqual(['None', 'See it', 'Put agents on it']);
        expect(levelWords('connection', 'use')).toBe('Can use');
    });

    it('offers Share on the account’s machines, never on an agent’s sandbox', () => {
        const kept = row({ ref: 'mch_ops', machine: { id: 'mch_ops', kind: 'machine', machineId: 'mch_ops', agentId: null, state: 'stopped' } });
        const sandbox = row({ ref: 'nc-live-1', machine: { id: 'nc-live-1', kind: 'sandbox', machineId: null, agentId: 'agt_builder', state: 'up' } });
        expect(shareable(kept)).toBe(true);
        expect(shareable(sandbox)).toBe(false);
        const linked = { ...kept, link: { id: 'lnk_ops', kind: 'machine' as const, ref: 'mch_ops', name: 'ops-box', membersLevel: 'run', guestsLevel: 'none', levels: ['none', 'run', 'use'], addedBy: null, addedAt: null, raw: {} } };
        expect(shareable(linked)).toBe(false);
    });

    it('knows a computer of yours by the summary where the account’s own read isn’t there', () => {
        expect(ownMachine(row({ ref: 'mch_dev', machine: { id: 'mch_dev', kind: 'machine', machineId: 'mch_dev', agentId: null, state: 'running', own: true } }))).toBe(true);
        expect(ownMachine(row({ ref: 'mch_ops', machine: { id: 'mch_ops', kind: 'machine', machineId: 'mch_ops', agentId: null, state: 'stopped' } }))).toBe(false);
    });
});
