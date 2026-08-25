// Shared data shapes for the usage surfaces (UsageDashboard, UsageDrawer).
// These mirror the wire format of usage_dashboard_handler.py — every numeric
// cost field is in credits ($→credits conversion happens once at the backend
// boundary; the frontend does no unit math). Extracted so the dashboard and
// drawer stop declaring drifting private copies.

/** One day-bucket of the cost time series. `date` is a UTC day key
 * ('YYYY-MM-DD', or 'YYYY-MM' for month grouping) — the backend buckets with
 * Postgres DATE_TRUNC in UTC, so all display/merge logic must stay in UTC. */
export interface TimeSeriesEntry {
    date: string;
    total_cost: number;
    by_type: Record<string, number>;
    by_subtype: Record<string, number>;
    tokens_by_subtype: Record<string, number>;
}

export interface UsageData {
    total_cost: number;
    usage_by_type: Record<string, number>;
    usage_by_subtype: Record<string, number>;
    /** Unit each subtype charges in (tokens / seconds / requests / …).
     * Optional: IndexedDB-cached responses from before the field existed lack
     * it; the 5-minute cache TTL self-heals. */
    units_by_subtype?: Record<string, string>;
    time_series: TimeSeriesEntry[];
    period_start: string | null;
    period_end: string | null;
    error?: string;
}

export interface UsageLogEntry {
    timestamp: string;
    // High-level category from the usage_event row — ai_builder is the workflow
    // graph generator, ai_usage is an in-workflow LLM call / agent node, api_usage
    // is third-party APIs, and cpu/gpu_usage are compute resources.
    // Optional for forward-compat; legacy cached entries may not include it.
    usage_type?: string;
    model: string;
    tokens: number;
    // Unit for `tokens` (which is really "quantity"): tokens for LLMs, seconds for
    // compute, requests for API nodes, and images/videos for media. Backend always
    // sends it; optional here for forward-compat with legacy cached entries.
    unit_type?: string;
    cost: number;
    metadata?: Record<string, unknown>;
}

export interface UsageLogsData {
    logs: UsageLogEntry[];
    count: number;
    /** Whether older events exist past the last row (drives infinite scroll).
     * Optional: cached/legacy responses predate the field. */
    has_more?: boolean;
}

/** Cache wrapper stored in useCachedValtioState — `timestamp` is the FETCH
 * time and drives the TTL check. Real-time merges deliberately do NOT bump it
 * (see lib/usage/events.ts), so incrementally-patched data still expires five
 * minutes after the last full fetch. */
export interface CachedUsageData {
    data: UsageData;
    timestamp: number;
}
