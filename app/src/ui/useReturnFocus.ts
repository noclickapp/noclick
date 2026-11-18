// For a dialog opened without a DialogTrigger: Radix hands focus back to the
// trigger on close, and with none it fell to the page. Spread these onto
// DialogContent to give it back to whatever had it when the dialog opened.
import { useRef } from 'react';

export function useReturnFocus() {
    const opener = useRef<HTMLElement | null>(null);
    return {
        onOpenAutoFocus: () => {
            const el = document.activeElement;
            opener.current = el instanceof HTMLElement && el !== document.body ? el : null;
        },
        onCloseAutoFocus: (event: Event) => {
            const el = opener.current;
            opener.current = null;
            // Gone with the page it was on (the dialog led somewhere else): leave focus where that page puts it.
            if (!el?.isConnected) return;
            event.preventDefault();
            el.focus();
        },
    };
}
