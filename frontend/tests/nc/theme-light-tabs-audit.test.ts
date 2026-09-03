// Light-mode contrast audit across the dashboard's feed and settings tabs
// (theme-light-audit.test.ts covers the default workflows view). Switches tab,
// scans visible text for unreadably low contrast, then restores tab + theme.
import { nc } from '~/lib/nc';
import { setTheme, getStoredTheme } from '~/lib/theme';

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
    if (m[4] !== undefined && parseFloat(m[4]) < 0.4) return null;
    const [r, g, b] = [+m[1], +m[2], +m[3]].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function scan() {
    const offenders: Array<{ text: string; color: string; bg: string; cls: string }> = [];
    const els = Array.from(document.querySelectorAll('body *')).filter((el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 5 || r.height < 5 || r.bottom < 0 || r.top > innerHeight) return false;
        return Array.from(el.childNodes).some(
            (n) => n.nodeType === 3 && (n.textContent || '').trim().length > 1
        );
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
                cls: (el.className?.toString() || '').slice(0, 90),
            });
        }
    }
    return { scanned: els.length, offenders };
}

export default async function () {
    const originalTheme = getStoredTheme();
    const freeze = document.createElement('style');
    freeze.textContent = '* { transition: none !important; animation: none !important; }';
    document.head.appendChild(freeze);
    setTheme('light');

    const results: Record<string, { scanned: number; offenders: unknown[] }> = {};
    for (const tab of ['dashboard', 'settings']) {
        window.dispatchEvent(
            new CustomEvent('noclick:switch-tab', { detail: { tab } })
        );
        await new Promise((r) => setTimeout(r, 700));
        const { scanned, offenders } = scan();
        results[tab] = { scanned, offenders: offenders.slice(0, 15) };
    }

    // Back to workflows + original theme
    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'flow' } }));
    setTheme(originalTheme);
    await new Promise((r) => setTimeout(r, 100));
    freeze.remove();

    nc.assert.gt(results.dashboard.scanned, 5, 'dashboard tab should render content');
    nc.assert.gt(results.settings.scanned, 5, 'settings tab should render content');
    return results;
}
