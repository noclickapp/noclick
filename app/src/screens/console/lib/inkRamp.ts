// Chart series colours: foreground ink at stepped alphas, so a chart follows the
// theme with no palette of its own. Series are ordered by size; the largest
// gets the darkest step and "Other" the faintest. Red is for an error series only.

const DARKEST = 0.85;
const FAINTEST = 0.16;

export function ink(alpha: number): string {
    return `hsl(var(--foreground) / ${Number(alpha.toFixed(3))})`;
}

/** `n` steps, darkest first. */
export function inkRamp(n: number): string[] {
    if (n <= 0) return [];
    if (n === 1) return [ink(DARKEST)];
    return Array.from({ length: n }, (_, i) => ink(DARKEST - ((DARKEST - FAINTEST) * i) / (n - 1)));
}

/** The one colour an error series may use (a fill class, so it follows the theme). */
export const ERROR_SERIES_CLASS = 'fill-red-600 dark:fill-red-400';
