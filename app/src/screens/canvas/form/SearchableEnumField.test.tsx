// @vitest-environment happy-dom
// Leaving the field closes its list a moment later, and inserting a reference puts the cursor after it a task later;
// once the field has gone, neither is left pending.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getInsertReferenceForField } from './DroppableTextField';
import { SearchableEnumField } from './SearchableEnumField';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const field = () => render(<SearchableEnumField fieldKey="priority" value="" enumValues={['low', 'high']} onChange={() => undefined} />);

describe('a searchable choice’s timers', () => {
    it('closes its list a moment after the field loses focus', () => {
        field();
        const input = screen.getByRole('textbox');
        fireEvent.focus(input);
        expect(screen.getByText('high')).toBeTruthy();
        fireEvent.blur(input);
        act(() => vi.advanceTimersByTime(150));
        expect(screen.queryByText('high')).toBeNull();
    });

    it('leaves nothing pending once it has gone', () => {
        const view = field();
        const input = screen.getByRole('textbox');
        fireEvent.focus(input);
        fireEvent.blur(input);
        act(() => getInsertReferenceForField('priority')?.('{{ $("a").b }}'));
        expect(vi.getTimerCount()).toBe(2);
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
    });
});
