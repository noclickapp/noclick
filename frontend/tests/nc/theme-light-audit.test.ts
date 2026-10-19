// Light-mode audit: flips the dashboard to light, scans visible text elements
// for unreadably low contrast against their effective background (conversion
// misses), verifies the route gate re-forces dark off /dashboard, then restores
// the original theme.
import { nc } from '~/lib/nc';
import {
    applyTheme,
    setTheme,
    getStoredTheme,
    isThemedPath,
} from '~/lib/theme';

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
    freeze.textContent =
        '* { transition: none !important; animation: none !important; }';
    document.head.appendChild(freeze);
    setTheme('light');
    await new Promise((r) => setTimeout(r, 300));

    const offenders: Array<{
        text: string;
        color: string;
        bg: string;
        cls: string;
    }> = [];
    const els = Array.from(document.querySelectorAll('body *')).filter((el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 5 || r.height < 5 || r.bottom < 0 || r.top > innerHeight)
            return false;
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

    // Route gates: with a light preference, the dashboard and the marketing pages go light, and
    // the paths still built dark-only (the docs, shared links) keep forcing dark.
    setTheme('light');
    applyTheme('/pricing');
    const pricingLight = !document.documentElement.classList.contains('dark');
    applyTheme('/integrations/slack');
    const integrationsLight = !document.documentElement.classList.contains('dark');
    applyTheme('/docs/guide/getting-started');
    const docsForcedDark = document.documentElement.classList.contains('dark');
    applyTheme('/dashboard');
    const dashboardLight = !document.documentElement.classList.contains('dark');

    // Restore the user's original theme
    setTheme(originalTheme);
    await new Promise((r) => setTimeout(r, 100));
    freeze.remove();

    nc.assert.equal(pricingLight, true, '/pricing honors a light preference');
    nc.assert.equal(integrationsLight, true, '/integrations/* honors a light preference');
    nc.assert.equal(docsForcedDark, true, '/docs stays dark');
    nc.assert.equal(dashboardLight, true, '/dashboard honors light preference');
    nc.assert.truthy(isThemedPath('/') && isThemedPath('/pricing'), 'the landing and /pricing are themed');
    for (const path of ['/templates', '/agents/codex', '/alternatives/zapier', '/mcp', '/app-builder', '/workflow/some-template', '/privacy-policy', '/auth/login']) {
        nc.assert.truthy(isThemedPath(path), `${path} is themed`);
    }
    nc.assert.falsy(isThemedPath('/docs') || isThemedPath('/share/abc'), 'the docs and shared links are not themed');
    nc.assert.truthy(isThemedPath('/dashboard'), 'dashboard is themed');

    return {
        scannedElements: els.length,
        lowContrast: offenders.slice(0, 25),
        lowContrastCount: offenders.length,
        pricingLight,
        integrationsLight,
        docsForcedDark,
        dashboardLight,
        restoredTo: originalTheme,
    };
}
