// Autocomplete for a chat textarea's trigger tokens, the way Slack's composer
// offers them: `@` for people and agents, `/` for commands at the start of a
// message, `:` for emoji. Each source says what its trigger finds and what a
// pick puts in the text; the hook follows the token under the caret, the
// highlighted row and the menu's keys (which must win over Enter-to-send, so
// the composer asks `onKeyDown` first).
import { useMemo, useState, type KeyboardEvent, type RefObject } from 'react';
import { applyMention, detectMentionToken, type MentionToken } from '~/utils/mentionToken';

const MAX_ITEMS = 8;

export interface AutocompleteSource<T> {
    trigger: string;
    /** Only as the message's first character, as slash commands are. */
    atStart?: boolean;
    /** Characters typed after the trigger before suggestions show. */
    minQuery?: number;
    search: (query: string) => T[];
    /** What a pick puts in place of the token; a space follows it. */
    insert: (item: T) => string;
}

export interface AutocompleteMatch<T> {
    source: AutocompleteSource<T>;
    query: string;
    items: T[];
}

interface OpenToken {
    trigger: string;
    token: MentionToken;
}

function findToken<T>(sources: AutocompleteSource<T>[], value: string, caret: number): OpenToken | null {
    for (const source of sources) {
        const token = detectMentionToken(value, caret, source.trigger);
        if (!token || (source.atStart && token.start !== 0) || token.query.length < (source.minQuery ?? 0)) continue;
        return { trigger: source.trigger, token };
    }
    return null;
}

export function useComposerAutocomplete<T>({
    sources,
    textareaRef,
    onChange,
}: {
    sources: AutocompleteSource<T>[];
    textareaRef: RefObject<HTMLTextAreaElement | null>;
    onChange: (value: string) => void;
}) {
    const [open, setOpen] = useState<OpenToken | null>(null);
    const [index, setIndex] = useState(0);
    // Esc closes the menu for this token only; the next one opens it again.
    const [dismissedAt, setDismissedAt] = useState<number | null>(null);

    const match = useMemo((): AutocompleteMatch<T> | null => {
        const source = open && sources.find((s) => s.trigger === open.trigger);
        if (!open || !source || dismissedAt === open.token.start) return null;
        const items = source.search(open.token.query).slice(0, MAX_ITEMS);
        return items.length ? { source, query: open.token.query, items } : null;
    }, [open, sources, dismissedAt]);
    const active = match ? Math.min(index, match.items.length - 1) : 0;

    /** Re-read the token under the caret: after typing, clicking or a programmatic edit. */
    const sync = (el: HTMLTextAreaElement) => {
        const found = el.selectionStart === el.selectionEnd ? findToken(sources, el.value, el.selectionStart) : null;
        if (found?.token.query !== open?.token.query || found?.trigger !== open?.trigger) setIndex(0);
        if (!found) setDismissedAt(null);
        setOpen(found);
    };

    const accept = (at: number = active) => {
        const el = textareaRef.current;
        const item = match?.items[at];
        if (!el || !match || !open || item === undefined) return;
        const next = applyMention(el.value, el.selectionStart, open.token, match.source.insert(item));
        onChange(next.value);
        setOpen(null);
        requestAnimationFrame(() => {
            el.focus();
            el.setSelectionRange(next.caret, next.caret);
        });
    };

    /** The menu's keys while it is open. True when the key was used. */
    const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
        if (!match || !open) return false;
        const count = match.items.length;
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                setIndex((active + 1) % count);
                return true;
            case 'ArrowUp':
                e.preventDefault();
                setIndex((active - 1 + count) % count);
                return true;
            case 'Enter':
            case 'Tab':
                if (e.shiftKey || e.nativeEvent.isComposing) return false;
                e.preventDefault();
                accept();
                return true;
            case 'Escape':
                e.preventDefault();
                e.stopPropagation();
                setDismissedAt(open.token.start);
                return true;
        }
        return false;
    };

    return { match, active, setActive: setIndex, accept, sync, close: () => setOpen(null), onKeyDown };
}
