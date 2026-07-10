// Light-mode audit: flips the dashboard to light, scans visible text elements
// for unreadably low contrast against their effective background (conversion
// misses), verifies the theme applies globally (no route gate), then restores
// the original theme.
import { nc } from '~/lib/nc';
import { applyTheme, setTheme, getStoredTheme } from '~/lib/theme';

function effectiveBg(el: Element): string | null {
    let node: Element | null = el;
    while (node) {
        const bg = getComputedStyle(node).backgroundColor;
        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
        node = node.parentElement;
    }
    return null;
}

function luminance(rgb: string): number | null {
    const m = rgb.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/);
    if (!m) return null;
    if (m[4] !== undefined && parseFloat(m[4]) < 0.4) return null; // too translucent to judge
    const [r, g, b] = [+m[1], +m[2], +m[3]].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export default async function () {
    const originalTheme = getStoredTheme();
    // Freeze transitions: in a backgrounded tab the transition clock doesn't
    // advance, so transitioned colors would be measured at their pre-flip values.
    const freeze = document.createElement('style');
    freeze.textContent = '* { transition: none !important; animation: none !important; }';
    document.head.appendChild(freeze);
    setTheme('light');
    await new Promise((r) => setTimeout(r, 300));

    const offenders: Array<{ text: string; color: string; bg: string; cls: string }> = [];
    const els = Array.from(document.querySelectorAll('body *')).filter((el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 5 || r.height < 5 || r.bottom < 0 || r.top > innerHeight) return false;
        const direct = Array.from(el.childNodes).some(
            (n) => n.nodeType === 3 && (n.textContent || '').trim().length > 1
        );
        return direct;
    });
    for (const el of els) {
        const st = getComputedStyle(el);
        if (st.visibility === 'hidden' || +st.opacity < 0.4) continue;
        const fg = luminance(st.color);
        const bgColor = effectiveBg(el);
        const bg = bgColor ? luminance(bgColor) : null;
        if (fg === null || bg === null) continue;
        const ratio = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
        if (ratio < 1.6) {
            offenders.push({
                text: (el.textContent || '').trim().slice(0, 40),
                color: st.color,
                bg: bgColor!,
                cls: (el.className?.toString() || '').slice(0, 80),
            });
        }
    }

    // No route gate: applyTheme honors the stored preference on every route.
    setTheme('light');
    applyTheme();
    const lightApplied = !document.documentElement.classList.contains('dark');
    setTheme('dark');
    applyTheme();
    const darkApplied = document.documentElement.classList.contains('dark');

    // Restore the user's original theme
    setTheme(originalTheme);
    await new Promise((r) => setTimeout(r, 100));
    freeze.remove();

    nc.assert.equal(lightApplied, true, 'light preference applies globally');
    nc.assert.equal(darkApplied, true, 'dark preference applies globally');

    return {
        scannedElements: els.length,
        lowContrast: offenders.slice(0, 25),
        lowContrastCount: offenders.length,
        lightApplied,
        darkApplied,
        restoredTo: originalTheme,
    };
}
