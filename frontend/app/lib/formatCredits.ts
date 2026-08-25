// Single formatter for credit amounts shown in the usage dashboard/drawer. Uses
// tier-appropriate precision: large amounts stay compact, but small amounts get
// enough decimals that they don't round misleadingly — a 30s sandbox interval is
// 0.025 credits (0.05 credits/min), which at 2 decimals looked like "0.03". Added
// to DRY the three copies that previously duplicated this logic.
//
// The "<0.0001 credits" floor is intentional: a 28-token gpt-4o-mini call
// genuinely costs ~0.00004 credits, and `(0.00004).toFixed(4)` rounds to
// "0.0000". Without the floor, real charges look like they got clipped to
// zero — distinguishing tiny-but-real from genuinely-zero matters when a
// user is auditing the log.

export function formatCredits(credits: number): string {
    if (credits === 0) return '0 credits';
    if (credits >= 100) return `${credits.toFixed(0)} credits`;
    if (credits >= 1) return `${credits.toFixed(1)} credits`;
    if (credits >= 0.1) return `${credits.toFixed(2)} credits`;
    if (credits >= 0.001) return `${credits.toFixed(3)} credits`;
    if (credits >= 0.0001) return `${credits.toFixed(4)} credits`;
    return '<0.0001 credits';
}
