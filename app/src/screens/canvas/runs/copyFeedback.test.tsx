// @vitest-environment happy-dom
// A copied output says so for two seconds, while it's shown; once the panel has gone, nothing is left pending.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DraggableJsonField } from './DraggableJsonField';
import { IODataDisplay } from './IODataDisplay';

beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => undefined } });
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

async function copied(ui: ReactElement, title: string) {
    const view = render(ui);
    await act(async () => {
        fireEvent.click(screen.getByTitle(title));
        await Promise.resolve();
    });
    return view;
}

const LONG = 'a note long enough to be drawn as a string that expands, well past the hundred characters it takes to be one';

describe.each([
    ['an output’s copy button', () => <IODataDisplay data={{ name: 'Ada' }} label="Output" />, 'Copy data'],
    ['a long value’s copy button', () => <DraggableJsonField data={LONG} nodeId="log" path="note" label="note" draggable={false} />, 'Copy to clipboard'],
])('%s', (_, ui, title) => {
    it('says copied, then goes back after two seconds', async () => {
        await copied(ui(), title);
        expect(vi.getTimerCount()).toBe(1);
        act(() => vi.advanceTimersByTime(2000));
        expect(vi.getTimerCount()).toBe(0);
    });

    it('leaves nothing pending once it has gone', async () => {
        const view = await copied(ui(), title);
        expect(vi.getTimerCount()).toBe(1);
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
    });
});
