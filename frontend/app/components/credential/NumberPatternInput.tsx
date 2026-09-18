// A ten-cell US number mask: type the digits or keypad letters you care about
// into their positions; blank cells match anything. Behaves like a code
// input — one hidden field carries focus and keys, the cells only show state.
import { useRef, useState } from 'react';
import { cn } from '~/lib/utils';
import { NUMBER_CELLS } from '~/lib/phoneFormat';

const GROUPS: [number, number][] = [[0, 3], [3, 6], [6, 10]];
const KEY = /^[0-9a-zA-Z]$/;

interface NumberPatternInputProps {
    cells: string[];
    onChange: (cells: string[]) => void;
    onSubmit?: () => void;
    disabled?: boolean;
}

export function NumberPatternInput({ cells, onChange, onSubmit, disabled }: NumberPatternInputProps) {
    const [active, setActive] = useState(0);
    const [focused, setFocused] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const set = (index: number, value: string) => {
        const next = Array.from({ length: NUMBER_CELLS }, (_, i) => cells[i] || '');
        next[index] = value;
        onChange(next);
    };
    const focusCell = (index: number) => {
        setActive(Math.max(0, Math.min(NUMBER_CELLS - 1, index)));
        inputRef.current?.focus();
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (disabled) return;
        if (e.key === 'Enter') { onSubmit?.(); return; }
        if (e.key === 'ArrowLeft') { e.preventDefault(); focusCell(active - 1); return; }
        if (e.key === 'ArrowRight') { e.preventDefault(); focusCell(active + 1); return; }
        if (e.key === 'Backspace') {
            e.preventDefault();
            if (cells[active]) set(active, '');
            else if (active > 0) { set(active - 1, ''); focusCell(active - 1); }
            return;
        }
        if (e.key === 'Delete') { e.preventDefault(); set(active, ''); return; }
        if (e.key === '*' || e.key === ' ' || e.key === '?') { e.preventDefault(); set(active, ''); focusCell(active + 1); return; }
        if (KEY.test(e.key)) {
            e.preventDefault();
            set(active, e.key.toUpperCase());
            focusCell(active + 1);
        }
    };

    const onPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
        e.preventDefault();
        const text = e.clipboardData.getData('text').toUpperCase().replace(/^\+?1(?=\d{10})/, '');
        const next = Array.from({ length: NUMBER_CELLS }, (_, i) => cells[i] || '');
        let index = active;
        for (const ch of text) {
            if (index >= NUMBER_CELLS) break;
            if (/[0-9A-Z]/.test(ch)) { next[index] = ch; index += 1; }
            else if (ch === '*' || ch === '?' || ch === '_') { next[index] = ''; index += 1; }
        }
        onChange(next);
        focusCell(index);
    };

    return (
        // The cells are buttons and the hidden input owns the keyboard, so the
        // frame itself only needs to hand a stray click to the active cell.
        <div
            className={cn(
                'inline-flex items-center gap-1 rounded-md border border-input bg-background px-2 py-1.5 font-mono text-sm',
                focused && 'ring-2 ring-ring ring-offset-1 ring-offset-background',
                disabled && 'opacity-60',
            )}
            onMouseDown={(e) => { e.preventDefault(); focusCell(active); }}
            role="presentation"
        >
            <span className="mr-1 text-muted-foreground">+1</span>
            {GROUPS.map(([start, end], g) => (
                <span key={g} className="flex items-center gap-1">
                    {g === 0 && <span className="text-muted-foreground">(</span>}
                    {g === 2 && <span className="text-muted-foreground">-</span>}
                    {Array.from({ length: end - start }, (_, k) => start + k).map((i) => {
                        const value = cells[i] || '';
                        const isActive = focused && active === i;
                        return (
                            <button
                                type="button"
                                key={i}
                                tabIndex={-1}
                                onClick={(e) => { e.stopPropagation(); focusCell(i); }}
                                className={cn(
                                    'flex h-7 w-5 items-center justify-center rounded-sm border-b-2 text-base leading-none',
                                    value ? 'border-foreground/70 text-foreground' : 'border-border text-muted-foreground/60',
                                    isActive && 'border-primary bg-primary/10',
                                )}
                                aria-label={value ? `position ${i + 1}: ${value}` : `position ${i + 1}: any digit`}
                            >
                                {value || '·'}
                            </button>
                        );
                    })}
                    {g === 0 && <span className="text-muted-foreground">)</span>}
                </span>
            ))}
            <input
                ref={inputRef}
                className="sr-only"
                value=""
                onChange={() => undefined}
                onKeyDown={onKeyDown}
                onPaste={onPaste}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                disabled={disabled}
                inputMode="text"
                autoComplete="off"
                aria-label="Type digits or letters into the number pattern"
            />
        </div>
    );
}
