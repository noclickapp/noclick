// `/` focuses the page's query bar or search, unless the viewer is typing.
import { useEffect, type RefObject } from 'react';
import { isTextEntryTarget } from '@/lib/keyboard';

export function useSlashFocus(ref: RefObject<HTMLInputElement | null>, enabled = true): void {
    useEffect(() => {
        if (!enabled) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || isTextEntryTarget(e.target)) return;
            e.preventDefault();
            ref.current?.focus();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [ref, enabled]);
}
