// Shared multi-value string list input. A trailing empty box is always
// present: typing into it autosaves (calls onChange on every keystroke, no
// Enter needed) and auto-appends a fresh empty box below, so users never press
// Enter to commit a value. Saved value is the rows trimmed with blanks dropped.
// Used by both the node config "list" widget (schemaWidgetRegistry) and the
// interface form ListField so the entry UX stays identical across surfaces.
import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

export function StringListInput({
    value,
    onChange,
    placeholder,
    inputClassName,
    trailingClassName = '',
}: {
    value: string[];
    onChange: (next: string[]) => void;
    placeholder?: string;
    /** Applied to every row input. */
    inputClassName: string;
    /** Extra classes for the trailing empty box (e.g. a dashed border). */
    trailingClassName?: string;
}) {
    const project = (rs: string[]) => rs.map(r => r.trim()).filter(r => r !== '');
    const [rows, setRows] = useState<string[]>(() => [...value, '']);
    const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

    // Adopt external value changes (AI builder edit, reference drop, reset)
    // without clobbering the in-progress trailing box: reset only when the
    // saved projection actually diverges from the incoming value.
    useEffect(() => {
        const current = project(rows);
        const same = current.length === value.length && current.every((v, i) => v === value[i]);
        if (!same) setRows([...value, '']);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value]);

    const commit = (next: string[]) => {
        setRows(next);
        onChange(project(next));
    };

    const handleChange = (index: number, raw: string) => {
        const next = [...rows];
        next[index] = raw;
        // Keep exactly one trailing empty box so the next value always has
        // somewhere to go without an explicit "add".
        if (index === next.length - 1 && raw.trim() !== '') next.push('');
        commit(next);
    };

    const removeRow = (index: number) => {
        const next = rows.filter((_, i) => i !== index);
        if (next.length === 0 || next[next.length - 1].trim() !== '') next.push('');
        commit(next);
    };

    return (
        <div className="space-y-1.5">
            {rows.map((item, i) => {
                const isTrailingEmpty = i === rows.length - 1 && item.trim() === '';
                return (
                    <div key={i} className="flex items-center gap-1.5 group">
                        <input
                            ref={el => { inputRefs.current[i] = el; }}
                            type="text"
                            className={`${inputClassName} ${isTrailingEmpty ? trailingClassName : ''}`}
                            placeholder={isTrailingEmpty ? (placeholder || 'Add item...') : undefined}
                            value={item}
                            onChange={e => handleChange(i, e.target.value)}
                            // Enter is optional now (typing autosaves); it just
                            // jumps to the next box, creating it if needed.
                            onKeyDown={e => {
                                if (e.key !== 'Enter') return;
                                e.preventDefault();
                                e.stopPropagation();
                                if (item.trim() === '') return;
                                if (i === rows.length - 1) commit([...rows, '']);
                                inputRefs.current[i + 1]?.focus();
                            }}
                        />
                        {!isTrailingEmpty && (
                            <button
                                type="button"
                                aria-label="Remove item"
                                onClick={() => removeRow(i)}
                                className="p-1 text-muted-foreground dark:text-zinc-500 hover:text-red-400 transition-colors"
                            >
                                <X className="w-3.5 h-3.5" />
                            </button>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
