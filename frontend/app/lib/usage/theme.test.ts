// Pins the color-assignment contract: keyed resource-type colors, and
// stable + collision-free series colors so a model keeps its color across
// views and date ranges.

import { describe, it, expect } from 'vitest';
import {
    assignSeriesColors,
    colorForUsageType,
    MODEL_COLORS,
    RESOURCE_TYPE_COLORS,
    usageTypeBadgeStyle,
} from './theme';

describe('colorForUsageType', () => {
    it('returns the keyed semantic color regardless of any ordering', () => {
        expect(colorForUsageType('api_usage')).toBe(
            RESOURCE_TYPE_COLORS.api_usage
        );
        expect(colorForUsageType('ai_usage')).toBe(
            RESOURCE_TYPE_COLORS.ai_usage
        );
    });

    it('falls back to a stable palette color for unknown types', () => {
        const c = colorForUsageType('some_future_type');
        expect(MODEL_COLORS).toContain(c);
        expect(colorForUsageType('some_future_type')).toBe(c);
    });
});

describe('assignSeriesColors', () => {
    it('is independent of caller ordering (bar sorts by cost, pie by value)', () => {
        const keys = [
            'gpt-4o',
            'claude-sonnet-5',
            'custom/compute',
            'twitter/x_api',
        ];
        const a = assignSeriesColors(keys);
        const b = assignSeriesColors([...keys].reverse());
        expect(a).toEqual(b);
    });

    it('never assigns the same color twice while the palette has capacity', () => {
        const keys = Array.from(
            { length: MODEL_COLORS.length },
            (_, i) => `model-${i}`
        );
        const colors = Object.values(assignSeriesColors(keys));
        expect(new Set(colors).size).toBe(keys.length);
    });

    it('assigns every key a palette color even past palette capacity', () => {
        const keys = Array.from(
            { length: MODEL_COLORS.length + 5 },
            (_, i) => `model-${i}`
        );
        const assigned = assignSeriesColors(keys);
        for (const key of keys) expect(MODEL_COLORS).toContain(assigned[key]);
    });
});

describe('usageTypeBadgeStyle', () => {
    it('tints every category badge with the exact rgb of its chart color', () => {
        for (const [type, hex] of Object.entries(RESOURCE_TYPE_COLORS)) {
            const n = parseInt(hex.slice(1), 16);
            const rgb = `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
            expect(usageTypeBadgeStyle(type).backgroundColor).toBe(
                `rgba(${rgb}, 0.15)`
            );
        }
    });

    it('gives unknown or missing categories a neutral chip', () => {
        // Theme-aware neutral: foreground/α inverts per mode (was hardcoded white).
        expect(usageTypeBadgeStyle('mystery_type').backgroundColor).toBe(
            'hsl(var(--foreground) / 0.06)'
        );
        expect(usageTypeBadgeStyle(undefined).color).toBe(
            'hsl(var(--foreground) / 0.5)'
        );
    });
});
