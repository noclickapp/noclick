// A region picker for console forms: the account's default region in Settings,
// and where a new sandbox or agent runs. It reads the regions from /v1/regions,
// so it names exactly what the API accepts.
import { cn } from '@/ui/utils';
import { FieldSelect } from '@/ui/FieldSelect';
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
            <FieldSelect
                id={id}
                value={value}
                disabled={!list.data}
                onValueChange={onChange}
                options={[{ value: '', label: empty }, ...(list.data ?? []).map((r) => ({ value: r.name, label: `${regionLabel(r.name, list.data)}: ${r.location}` }))]}
            />
            {hint && <p className="m-0 text-[12px] text-muted-foreground">{hint}</p>}
            {list.error !== undefined && !list.data && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">Couldn&apos;t load the regions.</p>}
        </div>
    );
}
