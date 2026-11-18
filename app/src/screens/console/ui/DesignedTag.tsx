// Marks something the lab draws that is a design: drawn ahead of the API, with nothing behind it yet. The real console
// never shows what it marks (the lab is the only place a `designed` page, kind or figure appears).
export function DesignedTag({ what = 'this' }: { what?: string }) {
    return (
        <span title={`Designed, not built yet: ${what} shows only in the lab.`} className="shrink-0 rounded-full border border-dashed border-foreground/[0.15] px-1.5 py-px text-[12px] font-medium text-foreground/55">
            designed
        </span>
    );
}
