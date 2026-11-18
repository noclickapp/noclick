// @vitest-environment happy-dom
// A slot shows what stands in it by default until a host fills it, the last fill stands, and a page already drawn
// follows a fill that lands late.
import { act, cleanup, render, screen } from '@testing-library/react';
import type { ComponentType } from 'react';
import { afterEach, expect, it } from 'vitest';
import { fill, slot, slots, standing, useSlot } from './slots';

afterEach(cleanup);

const LINE = slot<ComponentType<{ who: string }>>('test.line', ({ who }) => <p>Standard for {who}</p>);
const WORD = slot('test.word', 'standard');

function Page() {
    const Line = useSlot(LINE);
    return <Line who="Ana" />;
}

it('draws the standard until a host fills the slot, then the fill, and the last fill stands', () => {
    render(<Page />);
    expect(screen.getByText('Standard for Ana')).toBeTruthy();
    expect(slots().find((s) => s.name === 'test.line')).toEqual({ name: 'test.line', filled: false });

    // A fill that lands after the page drew (a module loaded late) shows at once.
    act(() => fill(LINE, ({ who }) => <p>A host’s line for {who}</p>));
    expect(screen.getByText('A host’s line for Ana')).toBeTruthy();
    expect(screen.queryByText('Standard for Ana')).toBeNull();

    act(() => fill(LINE, ({ who }) => <p>The host again, for {who}</p>));
    expect(screen.getByText('The host again, for Ana')).toBeTruthy();
    expect(slots().find((s) => s.name === 'test.line')).toEqual({ name: 'test.line', filled: true });
});

it('holds any value, read outside a component with standing()', () => {
    expect(standing(WORD)).toBe('standard');
    fill(WORD, 'filled');
    expect(standing(WORD)).toBe('filled');
});

it('keeps a fill when the module declaring the slot runs again', () => {
    // A development server runs a screen's slots module again on a change: the slot it declares then is the same place.
    const again = slot('test.word', 'standard');
    expect(standing(again)).toBe('filled');
});
