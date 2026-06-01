// Reusable keyboard-shortcut preview — renders small kbd chips in the shared
// style used across search affordances (sidebar search, workflow browser search)
// so keybinding hints stay visually consistent. Special tokens: 'mod' (⌘ on
// macOS, Ctrl elsewhere), 'shift', 'enter', 'esc', 'up', 'down'; any other
// string renders verbatim (e.g. 'K').
import { useIsMac } from '~/hooks/useIsMac';
import { cn } from '~/lib/utils';

const GLYPHS: Record<string, string> = {
    shift: '⇧',
    enter: '↵',
    esc: 'Esc',
    up: '↑',
    down: '↓',
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
