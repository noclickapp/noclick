/**
 * Compatibility surface for shared limit callers. The community edition has
 * no embedded plan catalogue; a missing entry is interpreted as unlimited.
 */
export type Tier = string;

export const PLAN_LIMITS: Record<
    string,
    { credentials_per_type?: number }
> = {};

export function formatLimit(value: number): string {
    return value === Infinity ? 'Unlimited' : String(value);
}

export function makeLimitErrorMessage(
    _tier: Tier,
    _limit: number | null,
    resource: string
): string {
    return `Instance limit reached: ${resource}. Check your instance configuration.`;
}
