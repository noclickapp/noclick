// Reusable keyboard-shortcut preview — renders small kbd chips in the shared
// style used across search affordances (sidebar search, workflow browser search)
// so keybinding hints stay visually consistent. Special tokens: 'mod' (⌘ on
// macOS, Ctrl elsewhere), 'shift', 'enter', 'esc', 'up', 'down', 'left',
// 'right', 'backspace'; any other string renders verbatim (e.g. 'K').
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
    backspace: '⌫',
};

interface KeyHintProps {
    keys: string[];
    className?: string;
}

export function KeyHint({ keys, className }: KeyHintProps) {
    const isMac = useIsMac();
    const label = (k: string) =>
        k === 'mod' ? (isMac ? '⌘' : 'Ctrl') : (GLYPHS[k] ?? k);
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
                    className="text-[10px] font-medium text-zinc-400 bg-white/[0.05] min-w-[17px] h-[17px] px-1 flex items-center justify-center rounded-[4px]"
                >
                    {label(k)}
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
                        <span className="text-[10px] text-zinc-500">then</span>
                    )}
                    <KeyHint keys={[k]} />
                </span>
            ))}
        </span>
    );
}
