// Markdown formatting on a controlled textarea: toolbar buttons, the ⌘B-style
// shortcuts, and Shift+Enter carrying a list on. Each change is one edit (see
// utils/markdownFormat), then the selection is put back where the person keeps
// typing and `onSelection` hears about it (an autocomplete re-reads the caret).
import { useCallback, type KeyboardEvent, type RefObject } from 'react';
import { applyFormat, continueList, formatForShortcut, insertText, type TextEdit, type TextFormat } from '~/utils/markdownFormat';

export function useTextFormatting(
    ref: RefObject<HTMLTextAreaElement | null>,
    onChange: (value: string) => void,
    onSelection?: (el: HTMLTextAreaElement) => void
) {
    const commit = useCallback(
        (edit: TextEdit) => {
            onChange(edit.value);
            // The controlled value lands on the next render; the selection after it.
            requestAnimationFrame(() => {
                const el = ref.current;
                if (!el) return;
                el.focus();
                el.setSelectionRange(edit.selectionStart, edit.selectionEnd);
                onSelection?.(el);
            });
        },
        [onChange, onSelection, ref]
    );

    const apply = useCallback(
        (format: TextFormat) => {
            const el = ref.current;
            if (el) commit(applyFormat(el.value, el.selectionStart, el.selectionEnd, format));
        },
        [commit, ref]
    );

    /** Put `text` over the selection, as if typed. */
    const insert = useCallback(
        (text: string) => {
            const el = ref.current;
            if (el) commit(insertText(el.value, el.selectionStart, el.selectionEnd, text));
        },
        [commit, ref]
    );

    /** The formatting shortcuts and list continuation. True when the key was used. */
    const onKeyDown = useCallback(
        (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
            const format = formatForShortcut(e);
            if (format) {
                e.preventDefault();
                apply(format);
                return true;
            }
            const el = e.currentTarget;
            if (e.key === 'Enter' && e.shiftKey && !e.nativeEvent.isComposing && el.selectionStart === el.selectionEnd) {
                const edit = continueList(el.value, el.selectionStart);
                if (edit) {
                    e.preventDefault();
                    commit(edit);
                    return true;
                }
            }
            return false;
        },
        [apply, commit]
    );

    return { apply, insert, commit, onKeyDown };
}
