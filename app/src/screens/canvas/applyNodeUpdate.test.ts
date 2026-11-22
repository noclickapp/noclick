import type { Node } from '@xyflow/react';
import { describe, expect, it } from 'vitest';
import {
    applyNodeStatuses,
    applyNodeUpdate,
    buildSaveConfig,
    createWorkflowNode,
    hasValidPosition,
    normalizeNodeUpdatePayload,
    rawConfigToPayload,
    serializeNodeForSave,
    updateNodeInList,
} from './applyNodeUpdate';

const slack = () =>
    createWorkflowNode('s', 'automation-slack', { x: 1, y: 2 }, { label: 'Tell the team', operation: 'send', channel: 'C1', credentialIds: { slack: 'c' } });

describe('a step as the canvas holds it', () => {
    it('keeps its settings under config and its metadata beside them', () => {
        const node = slack();
        expect(node).toMatchObject({ id: 's', type: 'automation-slack', position: { x: 1, y: 2 } });
        expect(node.data).toMatchObject({ label: 'Tell the team', operation: 'send', credentialIds: { slack: 'c' }, config: { channel: 'C1' } });
        expect((node.data.config as Record<string, unknown>).label).toBeUndefined();
    });

    it('takes an update: settings merge into config, metadata replaces, runtime goes in extras', () => {
        const node = applyNodeUpdate(slack(), { config: { text: 'hi' }, label: 'Page on-call', extras: { executionState: 'running' } });
        expect(node.data).toMatchObject({ label: 'Page on-call', executionState: 'running', config: { channel: 'C1', text: 'hi' } });
        expect(updateNodeInList([slack(), node], 's', { label: 'L' }).map((n) => n.data.label)).toEqual(['L', 'L']);
    });

    it('saves flat and loads back to the same data', () => {
        const node = slack();
        const saved = buildSaveConfig(node);
        expect(saved).toMatchObject({ label: 'Tell the team', operation: 'send', channel: 'C1', credentialIds: { slack: 'c' } });
        expect(createWorkflowNode('s', 'automation-slack', { x: 1, y: 2 }, saved).data).toEqual(node.data);
        expect(serializeNodeForSave(node)).toMatchObject({ id: 's', type: 'automation-slack', position: { x: 1, y: 2 } });
        expect(rawConfigToPayload(saved)).toMatchObject({ label: 'Tell the team', operation: 'send', config: { channel: 'C1' } });
    });

    it('holds what a read held back of its settings, never saving it or lifting it from a save', () => {
        const node = createWorkflowNode('h', 'http-request', { x: 0, y: 0 }, { url: 'https://x.test' }, { withheld: ['headers[0].value'] });
        expect(node.data.withheld).toEqual(['headers[0].value']);
        expect(buildSaveConfig(node)).toEqual({ url: 'https://x.test' });
        expect(applyNodeUpdate(node, { config: { url: 'https://y.test' } }).data.withheld).toEqual(['headers[0].value']);
        expect(rawConfigToPayload({ url: 'https://x.test', withheld: ['a'] })).not.toHaveProperty('withheld');
    });

    it('reads a loose update, unknown keys as extras', () => {
        expect(normalizeNodeUpdatePayload({ config: { a: 1 }, label: 'L', output: { ok: true } })).toEqual({ config: { a: 1 }, label: 'L', extras: { output: { ok: true } } });
    });

    it("lays a run's statuses on the steps it hasn't already marked", () => {
        const running = applyNodeUpdate(slack(), { extras: { executionState: 'running' } });
        const [done, kept] = applyNodeStatuses([slack(), running], { s: { status: 'completed', finishedAt: 5 } });
        expect(done.data).toMatchObject({ _lastRunStatus: 'completed', _lastRunAt: 5 });
        expect(kept).toBe(running);
    });

    it('knows a position it can draw at', () => {
        expect(hasValidPosition(slack())).toBe(true);
        expect(hasValidPosition({ ...slack(), position: { x: Number.NaN, y: 0 } } as Node)).toBe(false);
        expect(hasValidPosition(null)).toBe(false);
    });
});
