// The approval node's form fields, editable before deciding — the same field
// vocabulary the Approval node emits (string, number, boolean, select, list,
// schedule, media). Lifted from the retired Feed's card so the Dashboard's queue
// renders every field type the node can ask for, not just text.
import { Check } from 'lucide-react';
import { cn } from '~/lib/utils';
import type { AttentionField } from '~/components/dashboard/types';

const INPUT =
    'w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-[13px] text-foreground outline-none transition-colors placeholder:text-foreground/45 dark:placeholder:text-foreground/30 focus:border-foreground/30';

function Description({ text }: { text?: string }) {
    return text ? <p className="m-0 mt-1 text-[11.5px] text-foreground/60 dark:text-foreground/40">{text}</p> : null;
}

function MediaPreview({ url, label }: { url: string; label: string }) {
    const lower = url.toLowerCase();
    const isVideo = /\.(mp4|webm|mov|ogg)(\?|$)/i.test(lower) || lower.includes('video');
    const isAudio = /\.(mp3|wav|ogg|aac|m4a)(\?|$)/i.test(lower);
    return (
        <div className="overflow-hidden rounded-lg border border-border dark:border-foreground/[0.08] bg-foreground/[0.03]">
            {isVideo ? (
                <video src={url} controls className="max-h-[22rem] w-full object-contain">
                    <track kind="captions" />
                </video>
            ) : isAudio ? (
                <div className="p-3">
                    <audio src={url} controls className="w-full">
                        <track kind="captions" />
                    </audio>
                </div>
            ) : (
                <img src={url} alt={label} className="max-h-[22rem] w-full object-contain" />
            )}
            <a href={url} target="_blank" rel="noopener noreferrer" className="block truncate px-3 py-1.5 text-[11px] text-foreground/60 dark:text-foreground/40 hover:text-foreground">
                {url}
            </a>
        </div>
    );
}

export function ApprovalField({ field, value, onChange }: { field: AttentionField; value: unknown; onChange: (value: unknown) => void }) {
    const label = field.label || field.name;
    const text = value == null ? '' : String(value);

    if (field.type === 'boolean') {
        const checked = value === true || value === 'true';
        return (
            <label className="group/check flex cursor-pointer items-start gap-3 py-0.5">
                <span className={cn('mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded border transition-colors', checked ? 'border-primary bg-primary' : 'border-input group-hover/check:border-foreground/40')}>
                    {checked && <Check className="h-3 w-3 text-primary-foreground" />}
                </span>
                <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
                <span>
                    <span className="text-[13px] text-foreground/80">{label}</span>
                    <Description text={field.description} />
                </span>
            </label>
        );
    }

    return (
        <label className="block">
            <span className="mb-1 block text-[11.5px] text-foreground/65 dark:text-foreground/45">{label}</span>
            {field.type === 'media' ? (
                text ? (
                    <MediaPreview url={text.trim()} label={label} />
                ) : (
                    <div className="rounded-lg border border-border dark:border-foreground/[0.08] px-3 py-5 text-center text-[12px] text-foreground/55 dark:text-foreground/35">No media provided</div>
                )
            ) : field.type === 'select' && field.options ? (
                <select value={text} onChange={(e) => onChange(e.target.value)} className={INPUT}>
                    <option value="">Select…</option>
                    {field.options.map((o) => (
                        <option key={o} value={o}>
                            {o}
                        </option>
                    ))}
                </select>
            ) : field.type === 'text' || field.type === 'list' || text.length > 100 ? (
                <textarea value={text} onChange={(e) => onChange(e.target.value)} rows={3} className={cn(INPUT, 'resize-y leading-relaxed')} />
            ) : (
                <input
                    type={field.type === 'number' ? 'number' : 'text'}
                    value={text}
                    onChange={(e) => onChange(field.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)}
                    className={INPUT}
                />
            )}
            <Description text={field.description} />
        </label>
    );
}
