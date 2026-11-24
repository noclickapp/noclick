// @vitest-environment happy-dom
// A note's colour picker closes a moment after the pointer leaves it; once the note has gone, nothing is left pending.
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { ReactFlowProvider, type NodeProps } from '@xyflow/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StickyNote from './StickyNote';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const note = () =>
    render(
        <ReactFlowProvider>
            <StickyNote {...({ id: 'note', type: 'stickyNote', data: { content: 'Runs daily' }, selected: false } as unknown as NodeProps)} />
        </ReactFlowProvider>
    );

describe('a note’s colour picker', () => {
    it('closes a moment after the pointer leaves it', () => {
        const { container } = note();
        const picker = container.querySelector('.sticky-note-color-picker')!;
        fireEvent.mouseEnter(picker);
        fireEvent.mouseLeave(picker);
        expect(vi.getTimerCount()).toBe(1);
        act(() => vi.advanceTimersByTime(250));
        expect(vi.getTimerCount()).toBe(0);
    });

    it('leaves nothing pending once the note has gone', () => {
        const view = note();
        const picker = view.container.querySelector('.sticky-note-color-picker')!;
        fireEvent.mouseEnter(picker);
        fireEvent.mouseLeave(picker);
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
    });
});
