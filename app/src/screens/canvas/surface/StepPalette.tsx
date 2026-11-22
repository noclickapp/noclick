// The palette a step is added from, as this app draws it (the canvas's `canvas.palette` when no host fills it): every
// kind of step a workflow can hold, as the platform lists them (`stepTypes`, `GET /v1/step_types`: NoClick's own first,
// then the integrations most used; with a search, the best matches for it by name or by what they do), each with its
// glyph where the host loaded the catalog's, what it does and whether it starts runs or serves an agent as its tools.
// It fills whatever frames it. It holds its own search box unless the canvas around it does (`query`). Arrow keys move
// through the list, Enter adds, Escape closes.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Plus, Search, X } from 'lucide-react';
import { stepTypes, type StepType } from 'noclick';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { useDebounce } from '@/lib/useDebounce';
import { useClient } from '@/sdk/client';
import { errorText } from '@/screens/console/lib/errorText';
import { FIELD } from '@/ui/fields';
import { SerializedIcon } from '@/ui/SerializedIcon';
import { cn } from '@/ui/utils';
import type { CanvasPaletteProps } from '../slots';

/** How many steps a list shows: the first page of the platform's order, or of its matches. */
export const PALETTE_LIMIT = 30;

type Listing = { status: 'loading' } | { status: 'ready'; steps: StepType[] } | { status: 'failed'; message: string };

/** What a step serves as, beside its name. */
function kindsOf(step: StepType): string | null {
    const kinds = [step.kinds.includes('trigger') && 'Starts runs', step.kinds.includes('tool') && 'Agent tool'].filter(Boolean);
    return kinds.length ? kinds.join(' · ') : null;
}

function Glyph({ type }: { type: string }) {
    const meta = getNodeIconMeta(type);
    if (meta?.iconHtml) return <SerializedIcon html={meta.iconHtml} iconColor={meta.iconColor} className="h-5 w-5" />;
    return <span className="h-2 w-2 rounded-full bg-muted-foreground/60" aria-hidden />;
}

export default function StepPalette({ query: given, onClearQuery, onAdd, onClose }: CanvasPaletteProps) {
    const client = useClient();
    const [typed, setTyped] = useState('');
    const query = given ?? typed;
    const asked = useDebounce(query.trim(), 200);
    const [listing, setListing] = useState<Listing>({ status: 'loading' });
    const [active, setActive] = useState(0);
    const list = useRef<HTMLUListElement>(null);

    useEffect(() => {
        let live = true;
        setListing({ status: 'loading' });
        stepTypes(asked || undefined, { limit: PALETTE_LIMIT, client }).then(
            (steps) => {
                if (!live) return;
                setListing({ status: 'ready', steps });
                setActive(0);
            },
            (error: unknown) => live && setListing({ status: 'failed', message: errorText(error) })
        );
        return () => {
            live = false;
        };
    }, [client, asked]);

    const steps = listing.status === 'ready' ? listing.steps : [];

    useEffect(() => {
        list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView?.({ block: 'nearest' });
    }, [active]);

    const add = (step: StepType) => onAdd({ nodeType: step.type });

    const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Escape' && onClose) {
            event.preventDefault();
            onClose();
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (steps.length) setActive((i) => (i + (event.key === 'ArrowDown' ? 1 : steps.length - 1)) % steps.length);
        } else if (event.key === 'Enter' && steps[active]) {
            event.preventDefault();
            add(steps[active]);
        }
    };

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            {given === undefined && (
                <div className="relative flex items-center gap-1 p-1">
                    <Search className="pointer-events-none absolute left-4 h-4 w-4 text-muted-foreground" aria-hidden />
                    <input
                        autoFocus
                        value={typed}
                        onChange={(event) => setTyped(event.target.value)}
                        onKeyDown={onKeyDown}
                        placeholder="Search steps: send an email, a schedule…"
                        aria-label="Search steps"
                        className={cn(FIELD, 'h-9 pl-9')}
                    />
                    {onClose && (
                        <button type="button" onClick={onClose} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground">
                            <X className="h-4 w-4" />
                        </button>
                    )}
                </div>
            )}
            {listing.status === 'loading' && <p className="px-3 py-4 text-[13px] text-muted-foreground">Finding steps…</p>}
            {listing.status === 'failed' && <p className="px-3 py-4 text-[13px] text-red-600 dark:text-red-400">{listing.message}</p>}
            {listing.status === 'ready' && steps.length === 0 && (
                <div className="px-3 py-4 text-[13px] text-muted-foreground">
                    <p>{asked ? `No step matches “${asked}”.` : 'No steps to add.'}</p>
                    {asked && onClearQuery && (
                        <button type="button" onClick={onClearQuery} className="mt-2 font-medium text-foreground underline-offset-4 hover:underline">
                            Clear search
                        </button>
                    )}
                </div>
            )}
            {steps.length > 0 && (
                <ul ref={list} role="listbox" aria-label="Steps" className="min-h-0 overflow-y-auto">
                    {steps.map((step, index) => (
                        <li key={step.type} role="option" aria-selected={index === active} data-index={index}>
                            <button
                                type="button"
                                onMouseEnter={() => setActive(index)}
                                onClick={() => add(step)}
                                className={cn('flex w-full items-start gap-3 rounded-xl px-2.5 py-2 text-left', index === active && 'bg-foreground/[0.06]')}
                            >
                                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground/[0.05]">
                                    <Glyph type={step.type} />
                                </span>
                                <span className="min-w-0 flex-1">
                                    <span className="flex items-baseline gap-2">
                                        <span className="truncate text-[13.5px] font-medium text-foreground">{step.label ?? step.type}</span>
                                        {kindsOf(step) && <span className="shrink-0 text-[11.5px] text-muted-foreground">{kindsOf(step)}</span>}
                                    </span>
                                    {step.description && <span className="line-clamp-2 text-[12.5px] leading-snug text-muted-foreground">{step.description}</span>}
                                </span>
                                <Plus className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
