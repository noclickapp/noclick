// The community edition has no public marketing routes: `/` redirects into
// instance setup or the dashboard. Keep the shared root-loader API, but never
// suppress per-user loading for hosted routes that are not present here.

export const MARKETING_CACHE_CONTROL =
    'public, s-maxage=3600, stale-while-revalidate=86400, stale-if-error=86400';

export function marketingHeaders(): Record<string, string> {
    return { 'Cache-Control': MARKETING_CACHE_CONTROL };
}

export function isCacheableMarketingPath(_pathname: string): boolean {
    return false;
}
