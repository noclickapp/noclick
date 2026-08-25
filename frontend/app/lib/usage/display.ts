// Display mappings and formatters for usage data: subtype/category labels,
// badge accents and UTC-safe day formatting.
// Subsumes the old lib/usage-utils.ts so every usage surface labels rows the
// same way.

/**
 * Maps internal usage subtype identifiers to user-friendly display names.
 *
 * The stored `usage_subtype` is the source of truth — for ai_builder
 * events the BE writes a versioned sentinel like `noclick/builder-1`
 * instead of the raw model name (which is private). Version bumps map to
 * the same label via the prefix check below.
 */
const DISPLAY_NAMES: Record<string, string> = {
    'email/agent_reply': 'Email Reply',
    'email/send_node': 'Email Notification',
    ai_usage: 'AI',
    ai_builder: 'AI Builder',
    ai_testing: 'Agent Testing',
    cpu_usage: 'CPU',
    gpu_usage: 'GPU',
    api_usage: 'API',
    'twitter/x_api': 'X/Twitter API',
    // Instagram scraping (Apify-backed, no user credential required)
    'instagram/scrape_profile': 'Instagram: Scrape Profile',
    'instagram/scrape_posts': 'Instagram: Scrape Posts',
    'instagram/scrape_post': 'Instagram: Scrape Post',
    'instagram/scrape_hashtag': 'Instagram: Scrape Hashtag',
    'instagram/scrape_reels': 'Instagram: Scrape Reels',
    'instagram/scrape_comments': 'Instagram: Scrape Comments',
    // LinkedIn scraping (Apify-backed via harvestapi, no user credential required)
    'linkedin/scrape_profile': 'LinkedIn: Scrape Profile',
    'linkedin/search_companies': 'LinkedIn: Search Companies',
    'linkedin/search_jobs': 'LinkedIn: Search Jobs',
    'linkedin/search_profiles': 'LinkedIn: Search Profiles',
    'linkedin/scrape_company_employees': 'LinkedIn: Company Employees',
    'linkedin/search_posts': 'LinkedIn: Search Posts',
};

export const getDisplayName = (subtype: string): string => {
    if (subtype.startsWith('noclick/builder')) return 'AI Builder';
    if (subtype.startsWith('noclick/testing')) return 'Agent Testing';
    return DISPLAY_NAMES[subtype] || subtype;
};

/** Human-readable label for the usage_type category column. */
export const USAGE_TYPE_LABEL: Record<string, string> = {
    ai_builder: 'AI Builder',
    ai_testing: 'Agent Testing',
    ai_usage: 'Agent / LLM',
    api_usage: 'Third-party API',
    cpu_usage: 'Compute (CPU)',
    gpu_usage: 'Compute (GPU)',
};

// Category chip colors live in theme.ts (usageTypeBadgeStyle), derived from
// RESOURCE_TYPE_COLORS so badges always match the charts.

/**
 * Format a backend day-bucket key ('YYYY-MM-DD', or 'YYYY-MM' for month
 * grouping) for display. The buckets are UTC days, so formatting MUST pin
 * timeZone to UTC — `new Date('2026-07-03')` parses as UTC midnight and a
 * local-time formatter shifts it a day back for viewers west of UTC.
 */
export function formatUtcDay(
    dateKey: string,
    opts?: { short?: boolean }
): string {
    const iso =
        dateKey.length === 7
            ? `${dateKey}-01T00:00:00Z`
            : `${dateKey}T00:00:00Z`;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return dateKey;
    return date.toLocaleDateString('en-US', {
        month: opts?.short ? 'numeric' : 'short',
        day: 'numeric',
        timeZone: 'UTC',
    });
}
