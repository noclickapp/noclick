// Finds surfaces that stay dark in light mode: switches the dashboard to light,
// expands the chat sidebar, and reports every visible element whose computed
// background is still dark (the text-contrast audit can't catch these — dark
// panels with light text have fine contrast). Restores state afterwards.
import { setTheme, getStoredTheme } from '~/lib/theme';

function parseRgb(c: string): [number, number, number, number] | null {
    const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/);
    if (!m) return null;
    return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : parseFloat(m[4])];
}

function darkSurfaces(scope: string) {
    const out: Array<{ scope: string; tag: string; cls: string; bg: string; area: number }> = [];
    const seen = new Set<string>();
    for (const el of Array.from(document.querySelectorAll('body *'))) {
        const r = el.getBoundingClientRect();
        const area = r.width * r.height;
        if (area < 1500 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        const st = getComputedStyle(el);
        if (st.visibility === 'hidden' || +st.opacity < 0.3) continue;
        const rgb = parseRgb(st.backgroundColor);
        if (!rgb) continue;
        const [rr, gg, bb, a] = rgb;
        const lum = (0.299 * rr + 0.587 * gg + 0.114 * bb) / 255;
        if (a > 0.55 && lum < 0.35) {
            const cls = (el.className?.toString() || '').slice(0, 110);
            const sig = el.tagName + '|' + cls;
            if (seen.has(sig)) continue;
            seen.add(sig);
            out.push({ scope, tag: el.tagName, cls, bg: st.backgroundColor, area: Math.round(area) });
        }
    }
    return out.sort((x, y) => y.area - x.area).slice(0, 20);
}

export default async function () {
    const originalTheme = getStoredTheme();
    const freeze = document.createElement('style');
    freeze.textContent = '* { transition: none !important; animation: none !important; }';
    document.head.appendChild(freeze);
    setTheme('light');
    document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
    await new Promise((r) => setTimeout(r, 600));

    const results: Record<string, unknown> = {};
    results.workflowsTab = darkSurfaces('flow+sidebar');

    // KeyHint chips inside the navbar search button
    const search = document.querySelector('button[title="Search and run commands"]');
    if (search) {
        const kbd = search.querySelector('kbd');
        results.searchButton = {
            btnBg: getComputedStyle(search).backgroundColor,
            kbd: kbd
                ? { cls: kbd.className.slice(0, 110), bg: getComputedStyle(kbd).backgroundColor, color: getComputedStyle(kbd).color }
                : null,
        };
    }

    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'settings' } }));
    await new Promise((r) => setTimeout(r, 700));
    results.settingsTab = darkSurfaces('settings');

    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'flow' } }));
    document.dispatchEvent(new CustomEvent('noclick:sidebar:collapse'));
    setTheme(originalTheme);
    await new Promise((r) => setTimeout(r, 100));
    freeze.remove();
    return results;
}
