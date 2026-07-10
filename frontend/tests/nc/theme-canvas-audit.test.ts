// Light-mode audit of the workflow canvas: switches to light, opens the first
// workflow card, scans for surfaces that are still dark (conversion misses),
// then navigates back and restores the original theme.
import { setTheme, getStoredTheme } from '~/lib/theme';

function parseRgb(c: string): [number, number, number, number] | null {
    const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/);
    if (!m) return null;
    return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : parseFloat(m[4])];
}

function darkSurfaces() {
    const out: Array<{ tag: string; cls: string; bg: string; area: number }> = [];
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
            const fullCls = el.className?.toString() || '';
            // Inverted CTAs (bg-primary) render near-black in light mode by
            // design — user-confirmed; not a dark-surface leak.
            if (/\bbg-primary\b/.test(fullCls)) continue;
            const cls = fullCls.slice(0, 110);
            const sig = el.tagName + '|' + cls;
            if (seen.has(sig)) continue;
            seen.add(sig);
            out.push({ tag: el.tagName, cls, bg: st.backgroundColor, area: Math.round(area) });
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
    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'flow' } }));
    await new Promise((r) => setTimeout(r, 500));

    // Open the first workflow card (grid card with the group class from WorkflowBrowserCards)
    const card = document.querySelector('.grid .cursor-pointer.group') as HTMLElement | null;
    let canvasResult: unknown = 'no workflow card found';
    if (card) {
        card.click();
        // canvas is lazy-loaded; wait up to ~12s
        for (let i = 0; i < 24 && !document.querySelector('.react-flow'); i++) {
            await new Promise((r) => setTimeout(r, 500));
        }
        await new Promise((r) => setTimeout(r, 1500)); // let nodes render
        canvasResult = {
            canvasMounted: !!document.querySelector('.react-flow'),
            htmlDark: document.documentElement.classList.contains('dark'),
            darkSurfaces: darkSurfaces(),
        };
        window.dispatchEvent(new CustomEvent('noclick:workflow-browser-reset'));
        await new Promise((r) => setTimeout(r, 500));
    }

    setTheme(originalTheme);
    await new Promise((r) => setTimeout(r, 100));
    freeze.remove();
    return canvasResult;
}
