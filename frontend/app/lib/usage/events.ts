// Pure merge logic for real-time `usage:event` pushes into usage-dashboard
// data. Extracted from UsageDashboard/UsageDrawer, which each hand-rolled this
// three times INSIDE setState updaters — the cache writes nested in there were
// impure (double-applied under StrictMode) and read stale snapshots under
// event bursts. Keeping the merge pure lets callers apply it via functional
// updates, which is what makes it burst- and StrictMode-safe.

import type { UsageEventUpdateEvent } from '~/types/socket-events.generated';
import type {
    TimeSeriesEntry,
    UsageData,
    UsageLogEntry,
    UsageLogsData,
} from './types';

/** UTC day key ('YYYY-MM-DD') for a Date — matches the backend's
 * DATE_TRUNC('day') bucketing, which runs in UTC. */
export function utcDayKey(d: Date): string {
    return d.toISOString().slice(0, 10);
}

/** The UTC day bucket an event belongs to. Falls back to `nowMs` when the
 * event carries no timestamp (it just happened). */
export function usageEventDayKey(
    event: UsageEventUpdateEvent,
    nowMs: number = Date.now()
): string {
    return utcDayKey(
        new Date(event.timestamp ? event.timestamp * 1000 : nowMs)
    );
}

/**
 * Whether a live event belongs to the workspace view a component is showing.
 * Mirrors the backend query scope (usage_dashboard_handler._workspace_scope):
 *  - Org view: scope is organization_id = org (pooled across members), so
 *    match the event's org tag.
 *  - Personal view: scope is user_id = me across ALL workspaces, so match the
 *    charged pool owner (billing_user_id). Under organization attribution policy this includes
 *    spend from orgs I own (billed to me) and excludes orgs where I'm a
 *    non-owner member (billed to the owner). A null poolUserId (first read
 *    not landed yet) counts the event rather than dropping it — the next
 *    fetch reconciles.
 */
export function eventMatchesWorkspace(
    event: UsageEventUpdateEvent,
    workspaceId: string | null,
    poolUserId: string | null
): boolean {
    if (workspaceId) return (event.organization_id ?? null) === workspaceId;
    return !(
        poolUserId &&
        event.billing_user_id &&
        event.billing_user_id !== poolUserId
    );
}

/** Day-granular check that an event's bucket falls inside a displayed date
 * range. Only needed for custom HISTORICAL ranges (preset ranges end "now",
 * which always contains a live event); the comparison is in UTC day keys and
 * the next full refetch is the authoritative reconcile. */
export function eventWithinDayRange(
    event: UsageEventUpdateEvent,
    from: Date,
    to: Date,
    nowMs: number = Date.now()
): boolean {
    const key = usageEventDayKey(event, nowMs);
    return key >= utcDayKey(from) && key <= utcDayKey(to);
}

/**
 * Return a new UsageData with one live event merged in: totals, per-type and
 * per-subtype aggregates, the unit map, and the event's UTC day bucket in the
 * time series (inserted in sorted position if absent). Pure — never mutates
 * `prev` — so it is safe inside React functional updates and can be applied
 * to both live state and the preset caches from the same code path.
 */
export function applyEventToUsageData(
    prev: UsageData,
    event: UsageEventUpdateEvent,
    nowMs: number = Date.now()
): UsageData {
    const dayKey = usageEventDayKey(event, nowMs);
    const cost = event.total_cost;
    const subtype = event.usage_subtype;
    const type = event.usage_type;

    const idx = prev.time_series.findIndex((entry) => entry.date === dayKey);
    let timeSeries: TimeSeriesEntry[];
    if (idx >= 0) {
        const entry = prev.time_series[idx];
        // tokens_by_subtype gets ?? {} — drawer-cached entries predating the field
        // don't carry it.
        const tokens = entry.tokens_by_subtype ?? {};
        const updated: TimeSeriesEntry = {
            ...entry,
            total_cost: entry.total_cost + cost,
            by_type: {
                ...entry.by_type,
                [type]: (entry.by_type[type] || 0) + cost,
            },
            by_subtype: {
                ...entry.by_subtype,
                [subtype]: (entry.by_subtype[subtype] || 0) + cost,
            },
            tokens_by_subtype: {
                ...tokens,
                [subtype]: (tokens[subtype] || 0) + event.quantity,
            },
        };
        timeSeries = prev.time_series.map((e, i) => (i === idx ? updated : e));
    } else {
        timeSeries = [
            ...prev.time_series,
            {
                date: dayKey,
                total_cost: cost,
                by_type: { [type]: cost },
                by_subtype: { [subtype]: cost },
                tokens_by_subtype: { [subtype]: event.quantity },
            },
        ].sort((a, b) => a.date.localeCompare(b.date));
    }

    return {
        ...prev,
        total_cost: prev.total_cost + cost,
        usage_by_type: {
            ...prev.usage_by_type,
            [type]: (prev.usage_by_type[type] || 0) + cost,
        },
        usage_by_subtype: {
            ...prev.usage_by_subtype,
            [subtype]: (prev.usage_by_subtype[subtype] || 0) + cost,
        },
        // Keep the aggregated unit when we have one; a live event only fills gaps.
        units_by_subtype: {
            ...(prev.units_by_subtype ?? {}),
            [subtype]: prev.units_by_subtype?.[subtype] ?? event.unit_type,
        },
        time_series: timeSeries,
    };
}

/** Prepend a live event to the recent-events log, holding the list at
 * `limit` rows — pass `null` for no cap (a list the user has paginated
 * deeper must not be truncated back to one page by a live event). `count`
 * tracks the server-reported total, so it keeps incrementing past the cap.
 * `has_more` is preserved: prepending doesn't change what's older. */
export function prependUsageLog(
    prev: UsageLogsData | null,
    event: UsageEventUpdateEvent,
    limit: number | null = 20,
    nowMs: number = Date.now()
): UsageLogsData {
    const entry: UsageLogEntry = {
        timestamp: new Date(
            event.timestamp ? event.timestamp * 1000 : nowMs
        ).toISOString(),
        usage_type: event.usage_type,
        model: event.usage_subtype,
        tokens: event.quantity,
        unit_type: event.unit_type,
        cost: event.total_cost,
        metadata: {},
    };
    if (!prev) return { logs: [entry], count: 1 };
    const logs = [entry, ...prev.logs];
    return {
        ...prev,
        logs: limit !== null ? logs.slice(0, limit) : logs,
        count: prev.count + 1,
    };
}

/** Active filters for the recent-events log. */
export interface UsageLogFilters {
    search: string;
    usageType: string | null;
}

/**
 * Whether a live event belongs in the log under the active filters. Matches
 * the BACKEND's semantics exactly (usage_type equality + case-insensitive
 * substring on usage_subtype) so a prepended row never appears that the next
 * refetch would drop.
 */
export function eventMatchesLogFilters(
    event: UsageEventUpdateEvent,
    filters: UsageLogFilters
): boolean {
    if (filters.usageType && event.usage_type !== filters.usageType)
        return false;
    const query = filters.search.trim().toLowerCase();
    return !query || event.usage_subtype.toLowerCase().includes(query);
}
