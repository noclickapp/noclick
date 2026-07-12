// Reusable keyboard-shortcut preview — renders small kbd chips in the shared
// style used across search affordances (sidebar search, workflow browser search)
// so keybinding hints stay visually consistent. Special tokens: 'mod' (⌘ on
// macOS, Ctrl elsewhere), 'shift', 'enter', 'esc', 'up', 'down', 'left',
// 'right', 'backspace'; any other string renders verbatim (e.g. 'K').
// 'backspace' renders as a Lucide SVG instead of the U+232B glyph — the
// unicode char looks cramped/blurry inside a 17×17 keycap on most fonts.
import type { ReactNode } from 'react';
import { Delete } from 'lucide-react';
import { useIsMac } from '~/hooks/useIsMac';
import { cn } from '~/lib/utils';

const GLYPHS: Record<string, string> = {
    shift: '⇧',
    enter: '↵',
    esc: 'Esc',
    up: '↑',
    down: '↓',
    left: '←',
    right: '→',
};
const ICON_KEYS: Record<string, ReactNode> = {
    backspace: <Delete className="h-2.5 w-2.5" strokeWidth={2.25} />,
};

interface KeyHintProps {
    keys: string[];
    className?: string;
    /** Override the keycap (kbd) styling — e.g. brighter chips on a light/filled
     *  button. Merged over the default muted-chip look via cn(). */
    kbdClassName?: string;
}

export function KeyHint({ keys, className, kbdClassName }: KeyHintProps) {
    const isMac = useIsMac();
    const render = (k: string): ReactNode => {
        if (k === 'mod') return isMac ? '⌘' : 'Ctrl';
        if (k in ICON_KEYS) return ICON_KEYS[k];
        return GLYPHS[k] ?? k;
    };
    return (
        <span
            className={cn(
                'inline-flex items-center gap-[3px] select-none',
                className
            )}
        >
            {keys.map((k, i) => (
                <kbd
                    key={`${k}-${i}`}
                    className={cn(
                        // Single (non-dark:) bg so a kbdClassName override (e.g. the
                        // dark chip on the white Send button) can win via tailwind-merge
                        // — a dark: variant here outranks a base override and left the
                        // chip white-on-white. foreground/[0.1] reads as a chip on both
                        // the dark popover and light surfaces.
                        'text-[10px] font-medium text-muted-foreground bg-foreground/[0.1] ring-1 ring-foreground/10 dark:ring-0 min-w-[17px] h-[17px] px-1 flex items-center justify-center rounded-[4px]',
                        kbdClassName
                    )}
                >
                    {render(k)}
                </kbd>
            ))}
        </span>
    );
}

// Renders a leader sequence as "G then U" — the keys are pressed one after
// another, not together, so they read with an explicit "then" between keycaps.
export function SequenceKeyHint({
    keys,
    className,
}: {
    keys: string[];
    className?: string;
}) {
    return (
        <span className={cn('inline-flex items-center gap-1.5', className)}>
            {keys.map((k, i) => (
                <span
                    key={`${k}-${i}`}
                    className="inline-flex items-center gap-1.5"
                >
                    {i > 0 && (
                        <span className="text-[10px] text-muted-foreground dark:text-zinc-500">
                            then
                        </span>
                    )}
                    <KeyHint keys={[k]} />
                </span>
            ))}
        </span>
    );
}
