/** Visual-structure smoke test for /agents/:harness/:integration pages. */
import { nc } from '~/lib/nc';

export default async function () {
    nc.assert.truthy(
        /^\/agents\/[^/]+\/[^/]+$/.test(window.location.pathname),
        'an agent connection detail route should be open'
    );

    const page = document.querySelector(
        '[data-testid="agent-connect-detail-page"]'
    ) as HTMLElement | null;
    const hero = document.querySelector(
        '[data-testid="template-detail-hero"]'
    ) as HTMLElement | null;
    const preview = document.querySelector(
        '[data-testid="template-detail-preview"]'
    ) as HTMLElement | null;
    const sections = Array.from(
        document.querySelectorAll<HTMLElement>(
            '[data-testid="agent-connect-detail-page"] section[id]'
        )
    );

    nc.assert.truthy(page, 'the agent connection detail shell should mount');
    nc.assert.truthy(hero, 'the compact shared hero should render');
    nc.assert.truthy(
        preview?.querySelector('[data-testid="template-detail-preview-tint"]'),
        'the real workflow preview should use the subtle gradient tint'
    );
    nc.assert.gt(
        sections.length,
        2,
        'the existing connection-page content should remain available'
    );
    sections.forEach((section) =>
        nc.assert.equal(
            getComputedStyle(section).borderTopWidth,
            '0px',
            `${section.id} should use a borderless editorial surface`
        )
    );

    if (window.innerWidth >= 1024) {
        const toc = document.querySelector('aside') as HTMLElement | null;
        nc.assert.truthy(
            toc?.querySelector('nav a[href^="#"]'),
            'desktop connection pages should retain the slim contents rail'
        );
        nc.assert.truthy(
            Boolean(
                toc &&
                    hero &&
                    hero.getBoundingClientRect().left >=
                        toc.getBoundingClientRect().right
            ),
            'the hero should sit beside the contents rail'
        );
    }

    nc.assert.equal(
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
        'the connection detail page should not overflow horizontally'
    );

    return {
        path: window.location.pathname,
        sectionCount: sections.length,
    };
}
