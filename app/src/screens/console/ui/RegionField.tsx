// A region picker for console forms: the account's default region in Settings,
// and where a new sandbox or agent runs. It reads the regions from /v1/regions,
// so it names exactly what the API accepts.
import { cn } from '@/ui/utils';
import { ANYWHERE, regionLabel, useRegions } from '@/screens/console/hooks/useRegions';

/**
 * Where a new resource runs: a region, or '' for no choice. On a create form ''
 * takes the account's default (`emptyLabel` names it); in Settings '' clears it.
 */
export function RegionField({
    id,
    label = 'Region',
    value,
    onChange,
    emptyLabel,
    hint,
    className,
}: {
    id: string;
    label?: string;
    value: string;
    onChange: (value: string) => void;
    emptyLabel?: string;
    hint?: string;
    className?: string;
}) {
    const list = useRegions();
    const fallback = list.data?.find((r) => r.default);
    const empty = emptyLabel ?? (fallback ? `Your default, ${regionLabel(fallback.name, list.data)}` : ANYWHERE);
    return (
        <div className={cn('flex flex-col gap-1.5', className)}>
            <label htmlFor={id} className="text-[12px] font-medium text-muted-foreground">
                {label}
            </label>
            <select
                id={id}
                value={value}
                disabled={!list.data}
                onChange={(e) => onChange(e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-[13px] text-foreground outline-none [color-scheme:light] focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 dark:[color-scheme:dark]"
            >
                <option value="">{empty}</option>
                {list.data?.map((r) => (
                    <option key={r.name} value={r.name}>
                        {regionLabel(r.name, list.data)}: {r.location}
                    </option>
                ))}
            </select>
            {hint && <p className="m-0 text-[12px] text-muted-foreground">{hint}</p>}
            {list.error !== undefined && !list.data && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">Couldn&apos;t load the regions.</p>}
        </div>
    );
}
