// Pieces the Dicts and Queues panels share:
// a JSON value on one line for a list row, and the JSON textarea their write dialogs use
// (a dict's value, a queue's test message), which says where the JSON breaks.
import { cn } from '@/ui/utils';
import { INPUT } from './shared';

/** A JSON value on one line, cut to `max` characters: what a row shows of a value or a message body. */
export function jsonPreview(value: unknown, max = 120): string {
    const text = value === undefined ? '' : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export type JsonParse = { ok: true; value: unknown } | { ok: false; error: string };

/** Parse what someone typed as JSON; the parser's reason when it isn't. */
export function parseJson(text: string): JsonParse {
    if (!text.trim()) return { ok: false, error: 'Type a JSON value: an object, a list, a string in quotes, a number, true, false or null.' };
    try {
        return { ok: true, value: JSON.parse(text) };
    } catch (e) {
        return { ok: false, error: `That isn't JSON: ${e instanceof Error ? e.message : String(e)}` };
    }
}

/** A labelled JSON textarea; the parse error shows under it once there's something typed. */
export function JsonField({ id, label, value, onChange, rows = 6, hint }: { id: string; label: string; value: string; onChange: (text: string) => void; rows?: number; hint?: string }) {
    const parsed = parseJson(value);
    const invalid = value.trim() !== '' && !parsed.ok;
    return (
        <div className="flex flex-col gap-1.5">
            <label htmlFor={id} className="text-[12px] font-medium text-muted-foreground">
                {label}
            </label>
            <textarea
                id={id}
                rows={rows}
                spellCheck={false}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                aria-invalid={invalid || undefined}
                className={cn(INPUT, 'h-auto resize-y py-2 font-mono text-[13px] leading-relaxed', invalid && 'border-red-500/60 focus-visible:ring-red-500/40')}
            />
            {invalid && !parsed.ok ? (
                <span className="text-[12px] text-red-600 dark:text-red-400">{parsed.error}</span>
            ) : (
                hint && <span className="text-[12px] text-muted-foreground">{hint}</span>
            )}
        </div>
    );
}
