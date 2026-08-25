/**
 * Analytics calls are compatibility no-ops in the community build. Resolve a
 * stable label mechanically so the hosted product-event catalogue is not part
 * of this source tree and shared call sites do not need edition branches.
 */
export const EVENTS: Record<string, string> = new Proxy({}, {
    get: (_target, property) => String(property).toLowerCase(),
});

export type AnalyticsEvent = string;
