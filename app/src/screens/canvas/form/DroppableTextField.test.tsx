// @vitest-environment happy-dom
// Inserting a reference puts the cursor after it a task later; once the field has gone, nothing is left pending.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DroppableTextField, getInsertReferenceForField } from './DroppableTextField';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('a text field’s timers', () => {
    it('focuses the field after an inserted reference a task later', () => {
        render(<DroppableTextField fieldKey="subject" value="Hi " onChange={() => undefined} />);
        act(() => getInsertReferenceForField('subject')?.('{{ $("a").name }}'));
        expect(document.activeElement).not.toBe(screen.getByRole('textbox'));
        act(() => vi.advanceTimersByTime(0));
        expect(document.activeElement).toBe(screen.getByRole('textbox'));
    });

    it('leaves nothing pending once it has gone', () => {
        const view = render(<DroppableTextField fieldKey="subject" value="Hi " onChange={() => undefined} />);
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hi there' } });
        act(() => getInsertReferenceForField('subject')?.('{{ $("a").name }}'));
        expect(vi.getTimerCount()).toBe(2);
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
    });
});
