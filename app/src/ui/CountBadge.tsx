/** A count pill: a circle at minimum (min-width = height), a pill when the
 *  count is wider. Digits have no descender and a fractional tabular advance,
 *  so the centered line box leaves the ink high and a hair right; the nudges
 *  were measured at 8x. */
export function CountBadge({ count }: { count: number }) {
    return (
        <span className="inline-flex h-[20px] min-w-[20px] items-center justify-center rounded-full bg-primary px-1.5 text-primary-foreground">
            <span className="-translate-x-[0.4px] translate-y-[0.5px] text-[12px] font-semibold tabular-nums leading-none">{count}</span>
        </span>
    );
}
