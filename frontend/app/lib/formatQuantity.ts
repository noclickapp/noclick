// Format a usage quantity with its unit for the usage dashboard. Each charge stores a
// unit_type — tokens for LLMs, seconds for sandbox/CPU, requests for API nodes,
// images/videos for media — but the rows used to render every quantity as a bare
// number implicitly labelled "tokens". Large counts use K/M notation; the unit is
// singularized for a count of 1 ("1 request", not "1 requests").

export function formatQuantity(quantity: number, unit: string = 'tokens'): string {
    if (!quantity) return '-';
    const n =
        quantity >= 1_000_000 ? `${(quantity / 1_000_000).toFixed(1)}M`
        : quantity >= 1_000 ? `${(quantity / 1_000).toFixed(0)}K`
        : String(quantity);
    const label = quantity === 1 && unit.endsWith('s') ? unit.slice(0, -1) : unit;
    return `${n} ${label}`;
}
