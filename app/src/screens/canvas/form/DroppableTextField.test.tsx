// @vitest-environment happy-dom
// Inserting a reference puts the cursor after it a task later; once the field has gone, nothing is left pending.
// A reference with no step picked ($('')) is flagged rather than left looking fine.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { STEP_REFERENCE_SCAFFOLD, STEP_REFERENCE_SCAFFOLD_CARET } from '@/screens/canvas/expressionSyntax';
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

describe('an empty step reference', () => {
    it('is inserted with the caret between its quotes, where the step’s id goes', () => {
        function Field() {
            const [value, setValue] = useState('Hi ');
            return <DroppableTextField fieldKey="subject" value={value} onChange={setValue} />;
        }
        render(<Field />);
        act(() => getInsertReferenceForField('subject')?.(STEP_REFERENCE_SCAFFOLD, STEP_REFERENCE_SCAFFOLD_CARET));
        act(() => vi.advanceTimersByTime(0));
        const field = screen.getByRole('textbox') as HTMLInputElement;
        expect(field.value).toBe("Hi {{ $('') }}");
        expect(field.selectionStart).toBe("Hi {{ $('".length);
    });

    it('is flagged, where a picked step is not', () => {
        render(<DroppableTextField fieldKey="subject" value={"Hi {{ $('') }}"} onChange={() => undefined} />);
        expect(screen.getByTitle('Invalid references - click to remove all')).toBeTruthy();
        cleanup();
        render(<DroppableTextField fieldKey="subject" value={"Hi {{ $('a').name }}"} onChange={() => undefined} />);
        expect(screen.getByTitle('Remove references')).toBeTruthy();
    });
});
