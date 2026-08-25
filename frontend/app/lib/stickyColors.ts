// Sticky-note color palette (indexed color schemes), extracted from the
// StickyNote component so light, always-mounted surfaces (the workflow-browser
// graph preview) can tint sticky rects without importing the editor-heavy
// StickyNote module graph (@xyflow/react, MarkdownRenderer, CSS side effects).
//
// Each color carries BOTH a dark and a light scheme so stickies flip with the
// theme: dark is a deeply tinted near-black bg with light pastel text; light is
// a soft pastel bg with dark text. `border` is the muted rendered border so a
// sticky doesn't read as "selected" at rest. `accent` is the saturated hue
// (theme-independent) kept for spots that must pop: the color-picker swatches,
// the resizer handles, and the corner fold. Resolve with `stickyScheme()`.

interface StickyVariant {
    bg: string;
    border: string;
    text: string;
}
interface StickyColor {
    accent: string;
    dark: StickyVariant;
    light: StickyVariant;
}

export const stickyColors: Record<number, StickyColor> = {
    0: {
        accent: '#d97706',
        dark: {
            bg: 'rgba(41, 33, 11, 0.92)',
            border: '#78350f',
            text: '#fde68a',
        },
        light: { bg: '#fef9c3', border: '#fcd34d', text: '#713f12' },
    }, // Yellow
    1: {
        accent: '#dc2626',
        dark: {
            bg: 'rgba(45, 16, 16, 0.92)',
            border: '#7f1d1d',
            text: '#fecaca',
        },
        light: { bg: '#fee2e2', border: '#fca5a5', text: '#7f1d1d' },
    }, // Red
    2: {
        accent: '#2563eb',
        dark: {
            bg: 'rgba(16, 28, 48, 0.92)',
            border: '#1e3a8a',
            text: '#bfdbfe',
        },
        light: { bg: '#dbeafe', border: '#93c5fd', text: '#1e3a8a' },
    }, // Blue
    3: {
        accent: '#16a34a',
        dark: {
            bg: 'rgba(13, 36, 24, 0.92)',
            border: '#14532d',
            text: '#bbf7d0',
        },
        light: { bg: '#dcfce7', border: '#86efac', text: '#14532d' },
    }, // Green
    4: {
        accent: '#9333ea',
        dark: {
            bg: 'rgba(31, 18, 47, 0.92)',
            border: '#581c87',
            text: '#e9d5ff',
        },
        light: { bg: '#f3e8ff', border: '#d8b4fe', text: '#581c87' },
    }, // Purple
    5: {
        accent: '#db2777',
        dark: {
            bg: 'rgba(45, 16, 32, 0.92)',
            border: '#831843',
            text: '#fbcfe8',
        },
        light: { bg: '#fce7f3', border: '#f9a8d4', text: '#831843' },
    }, // Pink
    6: {
        accent: '#ea580c',
        dark: {
            bg: 'rgba(50, 25, 10, 0.92)',
            border: '#7c2d12',
            text: '#fed7aa',
        },
        light: { bg: '#ffedd5', border: '#fdba74', text: '#7c2d12' },
    }, // Orange
    7: {
        accent: '#71717a',
        dark: {
            bg: 'rgba(35, 35, 38, 0.92)',
            border: '#3f3f46',
            text: '#e4e4e7',
        },
        light: { bg: '#f4f4f5', border: '#d4d4d8', text: '#3f3f46' },
    }, // Gray
    8: {
        accent: '#525252',
        dark: {
            bg: 'rgba(30, 30, 30, 0.9)',
            border: '#525252',
            text: '#e5e5e5',
        },
        light: { bg: '#e5e5e5', border: '#a3a3a3', text: '#262626' },
    }, // Black
};

/** Flat {bg, border, accent, text} for a color index in the given theme.
 *  Out-of-range/missing indexes fall back to Black (8), matching the canvas. */
export function stickyScheme(
    index: number | undefined,
    isDark: boolean
): { bg: string; border: string; accent: string; text: string } {
    const c = stickyColors[index as number] ?? stickyColors[8];
    const v = isDark ? c.dark : c.light;
    return { accent: c.accent, bg: v.bg, border: v.border, text: v.text };
}
