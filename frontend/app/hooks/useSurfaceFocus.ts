// A composer is one box: pressing anywhere on it that isn't a control puts the
// caret in its text, as chat apps do. Without this only the textarea's own rows
// take a click, and the padding, the controls row's gaps and the tray around
// them do nothing.
import { useCallback, type MouseEvent, type RefObject } from 'react';

const CONTROLS =
    'button, a, input, textarea, select, label, audio, video, [role="button"], [role="slider"], [role="menu"], [role="menuitem"], [role="listbox"], [role="option"], [contenteditable="true"]';

/** The composer surface's `onMouseDown`. */
export function useSurfaceFocus(textareaRef: RefObject<HTMLTextAreaElement | null>) {
    return useCallback(
        (event: MouseEvent<HTMLElement>) => {
            if (event.button !== 0) return;
            if ((event.target as HTMLElement).closest(CONTROLS)) return;
            const el = textareaRef.current;
            if (!el || el.disabled) return;
            // Keep the press from taking focus away from (or before) the text.
            event.preventDefault();
            if (document.activeElement === el) return;
            el.focus();
            const end = el.value.length;
            el.setSelectionRange(end, end);
        },
        [textareaRef]
    );
}
