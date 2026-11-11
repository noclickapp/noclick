// @vitest-environment happy-dom
// Before the dashboard hydrates, the icon map its HTML preloads fills the registry, so its first render has the icons
// the server drew.
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.resetModules();
});

// The page's HTML as parsed, inert: nothing in it is fetched but by the code under test.
const page = (href?: string) => {
    const doc = document.implementation.createHTMLDocument();
    if (href) doc.head.innerHTML = `<link rel="preload" as="fetch" crossorigin="anonymous" href="https://noclick.com${href}">`;
    return doc;
};

describe('loadPreloadedNodeIcons', () => {
    it('fills the registry from the file the page preloads', async () => {
        const fetch = vi.fn(async () => new Response(JSON.stringify({ 'automation-slack': { type: 'automation-slack', label: 'Slack' } })));
        vi.stubGlobal('fetch', fetch);
        const icons = await import('~/lib/nodeIconRegistry');
        await icons.loadPreloadedNodeIcons(page(icons.nodeIconsPath('abc123')));
        expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/node-icons/abc123'));
        expect(icons.getNodeIconMeta('automation-slack')?.label).toBe('Slack');
    });

    it('waits for nothing on a page that preloads no icon map', async () => {
        const fetch = vi.fn();
        vi.stubGlobal('fetch', fetch);
        const icons = await import('~/lib/nodeIconRegistry');
        await icons.loadPreloadedNodeIcons(page());
        expect(fetch).not.toHaveBeenCalled();
    });

    it('says so and lets the page hydrate when the file doesn’t load', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 503 })));
        const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const icons = await import('~/lib/nodeIconRegistry');
        await expect(icons.loadPreloadedNodeIcons(page(icons.nodeIconsPath('abc123')))).resolves.toBeUndefined();
        expect(error).toHaveBeenCalled();
        expect(icons.getKnownNodeIconTypes()).toEqual([]);
    });
});
