/** Visual-structure smoke test for /agents and /agents/:harness. */
import { nc } from '~/lib/nc';

export default async function () {
    const isIndex = window.location.pathname === '/agents';
    const isHarness = /^\/agents\/[^/]+$/.test(window.location.pathname);

    nc.assert.truthy(
        isIndex || isHarness,
        'an agent index or harness page should be open'
    );

    const page = document.querySelector(
        isIndex
            ? '[data-testid="agents-index-page"]'
            : '[data-testid="agent-harness-page"]'
    ) as HTMLElement | null;
    const sections = Array.from(
        page?.querySelectorAll<HTMLElement>('section[id]') ?? []
    );

    nc.assert.truthy(page, 'the redesigned agent page shell should mount');
    nc.assert.falsy(
        document.querySelector('[data-testid="template-detail-backdrop"]'),
        'agent pages should have no ambient glow backdrop'
    );
    nc.assert.truthy(
        getComputedStyle(page!.querySelector('h1')!).fontFamily.includes('Instrument Serif'),
        'the page title should speak in the display serif'
    );
    nc.assert.gt(
        sections.length,
        1,
        'agent-page content should render in editorial sections'
    );
    sections.forEach((section) =>
        nc.assert.equal(
            getComputedStyle(section).borderTopWidth,
            '0px',
            `${section.id} should use a borderless editorial surface`
        )
    );

    if (isHarness) {
        nc.assert.truthy(
            document.querySelector('[data-testid="template-detail-preview"]'),
            'the live harness preview should render'
        );
        nc.assert.truthy(
            document.querySelector('button[aria-pressed]'),
            'interactive trigger and tool selection should remain intact'
        );
    }

    nc.assert.equal(
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
        'the redesigned agent page should not overflow horizontally'
    );

    return {
        path: window.location.pathname,
        variant: isIndex ? 'index' : 'harness',
        sectionCount: sections.length,
    };
}
