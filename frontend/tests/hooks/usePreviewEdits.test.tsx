// @vitest-environment jsdom
// A read-only canvas shows what changed between two reads of a graph the way the live canvas shows the builder editing
// a node: each node added or changed opens for a moment, then closes. Where motion is reduced (the OS setting, or a
// lab's switch above the canvas), nothing opens; the changed node fades in instead.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EDIT_HOLD_MS, graphEdits, usePreviewEdits } from '~/hooks/usePreviewEdits';
import type { ScaffoldBlob } from '~/lib/agentScaffold';

const node = (id: string, type: string, config: Record<string, unknown>, x = 0) => ({ id, type, position: { x, y: 0 }, config });
const AGENT = node('agent', 'agent', { label: 'OpenCode', model: 'opencode', opencode_model: 'opencode/big-pickle' });
const GMAIL = node('gmail-1', 'automation-gmail', { label: 'Gmail', operation: 'send_email' });
const BEFORE: ScaffoldBlob = { nodes: [AGENT, GMAIL], edges: [] };
const SWITCHED: ScaffoldBlob = { nodes: [{ ...AGENT, config: { ...AGENT.config, model: 'claude-code' } }, GMAIL], edges: [] };

describe('graphEdits', () => {
    it('reads a node added, and a node changed with the fields that changed', () => {
        const slack = node('slack-2', 'automation-slack', { operation: 'send_message' });
        expect(graphEdits(BEFORE, { nodes: [...SWITCHED.nodes, slack], edges: [] })).toEqual({
            agent: { status: 'complete', action: 'updated', operation: undefined, config: { model: 'claude-code' } },
            'slack-2': { status: 'complete', action: 'added', operation: 'send_message' },
        });
    });

    it('takes a move, or a node removed, as no edit', () => {
        expect(graphEdits(BEFORE, { nodes: [{ ...AGENT, position: { x: 400, y: 80 } }], edges: [] })).toEqual({});
    });
});

describe('usePreviewEdits', () => {
    let frame: HTMLDivElement;
    let card: HTMLDivElement;
    const animate = vi.fn();

    beforeEach(() => {
        vi.useFakeTimers();
        document.body.innerHTML = '<div data-motion="full"><div id="frame"><div class="react-flow__node" data-id="agent"></div></div></div>';
        frame = document.getElementById('frame') as HTMLDivElement;
        card = frame.querySelector('[data-id="agent"]') as HTMLDivElement;
        card.animate = animate;
    });
    afterEach(() => {
        vi.useRealTimers();
        animate.mockReset();
    });

    const mount = (enabled = true) => renderHook(({ blob }) => usePreviewEdits(blob, { current: frame }, enabled), { initialProps: { blob: BEFORE } });

    it('starts where the first read is, then opens what the next read changed, and closes it', () => {
        const { result, rerender } = mount();
        expect(result.current).toEqual({});
        rerender({ blob: SWITCHED });
        expect(result.current.agent).toMatchObject({ action: 'updated', config: { model: 'claude-code' } });
        act(() => vi.advanceTimersByTime(EDIT_HOLD_MS));
        expect(result.current).toEqual({});
        expect(animate).not.toHaveBeenCalled();
    });

    it('with motion reduced, opens nothing and fades the changed node in', () => {
        frame.parentElement!.setAttribute('data-motion', 'reduced');
        const { result, rerender } = mount();
        rerender({ blob: SWITCHED });
        expect(result.current).toEqual({});
        act(() => vi.advanceTimersByTime(100));
        expect(animate).toHaveBeenCalledWith([{ opacity: 0.2 }, { opacity: 1 }], expect.objectContaining({ duration: 600 }));
    });

    it('follows the OS setting where no lab switch is above the canvas', () => {
        frame.parentElement!.removeAttribute('data-motion');
        const matchMedia = vi.fn().mockReturnValue({ matches: true });
        vi.stubGlobal('matchMedia', matchMedia);
        const { result, rerender } = mount();
        rerender({ blob: SWITCHED });
        expect(result.current).toEqual({});
        expect(matchMedia).toHaveBeenCalledWith('(prefers-reduced-motion: reduce)');
        vi.unstubAllGlobals();
    });

    it('shows nothing where the canvas doesn’t ask for it', () => {
        const { result, rerender } = mount(false);
        rerender({ blob: SWITCHED });
        expect(result.current).toEqual({});
    });
});
