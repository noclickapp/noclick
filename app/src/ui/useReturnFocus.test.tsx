// @vitest-environment happy-dom
import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { useReturnFocus } from './useReturnFocus';

afterEach(() => {
    cleanup();
    document.body.replaceChildren();
});

function button(name: string): HTMLButtonElement {
    const element = document.createElement('button');
    element.textContent = name;
    document.body.append(element);
    return element;
}

/** What Radix hands `onCloseAutoFocus`: an event the handler may cancel to place focus itself. */
const closing = () => new Event('focus.autoFocusOnUnmount', { cancelable: true });

it('gives focus back to whatever had it when the dialog opened', () => {
    const opener = button('Rename');
    const { result } = renderHook(() => useReturnFocus());
    opener.focus();
    result.current.onOpenAutoFocus();
    button('Save').focus();

    const event = closing();
    result.current.onCloseAutoFocus(event);
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(opener);
});

it('leaves focus where the page puts it when the opener is gone, or nothing had focus', () => {
    const opener = button('Delete');
    const { result } = renderHook(() => useReturnFocus());
    opener.focus();
    result.current.onOpenAutoFocus();
    opener.remove();
    const gone = closing();
    result.current.onCloseAutoFocus(gone);
    expect(gone.defaultPrevented).toBe(false);

    (document.activeElement as HTMLElement | null)?.blur();
    result.current.onOpenAutoFocus();
    const nothing = closing();
    result.current.onCloseAutoFocus(nothing);
    expect(nothing.defaultPrevented).toBe(false);
});

it('forgets the opener once the dialog has closed', () => {
    const opener = button('Share');
    const { result } = renderHook(() => useReturnFocus());
    opener.focus();
    result.current.onOpenAutoFocus();
    result.current.onCloseAutoFocus(closing());

    const again = closing();
    result.current.onCloseAutoFocus(again);
    expect(again.defaultPrevented).toBe(false);
});
