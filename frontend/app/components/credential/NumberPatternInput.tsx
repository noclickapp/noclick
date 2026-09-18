// The number picker's search control: a US number written as ten positions,
// on the panel's own surface. Type the digits or keypad letters you want
// where you want them; open positions show as underscores and match any
// digit. Behaves like a code input — one hidden field owns focus and keys,
// the cells only show state.
import { useRef, useState } from 'react';
import { cn } from '~/lib/utils';
import { NUMBER_CELLS, type PatternMode } from '~/lib/phoneFormat';

const GROUPS: [number, number][] = [[0, 3], [3, 6], [6, 10]];
const KEY = /^[0-9a-zA-Z]$/;

interface NumberPatternInputProps {
    cells: string[];
    onChange: (cells: string[]) => void;
    mode: PatternMode;
    onModeChange: (mode: PatternMode) => void;
    onSubmit?: () => void;
    disabled?: boolean;
}

export function NumberPatternInput({ cells, onChange, mode, onModeChange, onSubmit, disabled }: NumberPatternInputProps) {
    const [active, setActive] = useState(0);
    const [focused, setFocused] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const filled = cells.some(Boolean);

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
        if (e.key === '*' || e.key === ' ' || e.key === '?' || e.key === '_') { e.preventDefault(); set(active, ''); focusCell(active + 1); return; }
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
        <div
            className={cn(
                'rounded-lg border border-border bg-card p-3 transition-colors',
                focused && 'border-ring',
                disabled && 'opacity-60',
            )}
            role="presentation"
        >
            <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-foreground">Number</span>
                <div className="flex items-center gap-1 rounded-md bg-muted p-0.5 text-[11px]" role="radiogroup" aria-label="How the digits are matched">
                    {(['positions', 'anywhere'] as PatternMode[]).map((m) => (
                        <button
                            key={m}
                            type="button"
                            role="radio"
                            aria-checked={mode === m}
                            onClick={() => onModeChange(m)}
                            disabled={disabled}
                            className={cn(
                                'rounded px-2 py-0.5 transition-colors',
                                mode === m ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                            )}
                        >
                            {m === 'positions' ? 'In these positions' : 'Anywhere'}
                        </button>
                    ))}
                </div>
            </div>
            {/* The well hands a click to the active cell; the cells are buttons and the hidden input owns the keyboard. */}
            <div
                role="presentation"
                className="mt-2 flex items-center gap-1.5 rounded-md bg-muted/60 px-3 py-2 font-mono text-[15px]"
                onMouseDown={(e) => { e.preventDefault(); focusCell(active); }}
            >
                <span className="mr-1 text-muted-foreground">+1</span>
                {GROUPS.map(([start, end], g) => (
                    <span key={g} className="flex items-center gap-1">
                        {g === 2 && <span className="text-muted-foreground/70">–</span>}
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
                                        'flex h-7 w-5 items-center justify-center rounded-sm leading-none transition-colors',
                                        value ? 'text-foreground' : 'text-muted-foreground/50',
                                        isActive && 'bg-primary/15 ring-1 ring-primary/60',
                                    )}
                                    aria-label={value ? `position ${i + 1}: ${value}` : `position ${i + 1}: any digit`}
                                >
                                    {value || '_'}
                                </button>
                            );
                        })}
                        {g < 2 && <span className="w-1" />}
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
                    aria-label="Type digits or letters into the number"
                />
            </div>
            <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">
                {mode === 'positions'
                    ? filled
                        ? 'Underscores match any digit. Just the first three filled searches that area code.'
                        : 'Type digits or letters where you want them; letters spell on the keypad (NOCLICK). Leave the rest as underscores.'
                    : 'The digits or letters you type must appear somewhere in the number, in that order.'}
            </p>
        </div>
    );
}
