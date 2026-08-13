/**
 * Visual-structure smoke test for both /workflow/:slug and
 * /workflow/:slug/with/:harness template landing pages.
 */
import { nc } from '~/lib/nc';

export default async function () {
    nc.assert.truthy(
        /^\/workflow\/[^/]+(?:\/with\/[^/]+)?$/.test(window.location.pathname),
        'a public template detail route should be open'
    );

    const page = document.querySelector(
        '[data-testid="template-detail-page"]'
    ) as HTMLElement | null;
    const hero = document.querySelector(
        '[data-testid="template-detail-hero"]'
    ) as HTMLElement | null;
    const preview = document.querySelector(
        '[data-testid="template-detail-preview"]'
    ) as HTMLElement | null;
    const previewTint = preview?.querySelector(
        '[data-testid="template-detail-preview-tint"]'
    ) as HTMLElement | null;
    const title = hero?.querySelector('h1') as HTMLElement | null;
    const bottomCta = document.querySelector(
        '[data-testid="template-detail-bottom-cta"]'
    ) as HTMLElement | null;

    nc.assert.truthy(page, 'the redesigned template shell should mount');
    nc.assert.truthy(
        document.querySelector('[data-testid="template-detail-backdrop"]'),
        'template pages should share the soft editorial backdrop'
    );
    nc.assert.truthy(
        !hero?.className.includes('rounded-[2rem]'),
        'the hero should keep the original flat detail-page composition'
    );
    nc.assert.truthy(
        title?.className.includes('md:text-5xl'),
        'the template title should keep the original compact scale'
    );
    nc.assert.truthy(
        preview?.className.includes('h-[440px]'),
        'the real workflow should keep a useful fixed visual stage'
    );
    nc.assert.truthy(
        previewTint,
        'the preview should add only the templates gradient tint'
    );
    nc.assert.truthy(
        previewTint?.className.includes('from-chart-1/[0.035]'),
        'single-canvas detail previews should keep the gradient tint subtle'
    );
    nc.assert.truthy(
        bottomCta?.className.includes('dark:bg-zinc-950'),
        'the closing CTA should match the templates-page dark surface'
    );

    const sectionCards = Array.from(
        document.querySelectorAll<HTMLElement>(
            '[data-testid="template-detail-page"] section[id]'
        )
    );
    nc.assert.gt(
        sectionCards.length,
        0,
        'template detail content should render in editorial section cards'
    );
    sectionCards.forEach((section) =>
        nc.assert.equal(
            getComputedStyle(section).borderTopWidth,
            '0px',
            `${section.id} should use a borderless editorial surface`
        )
    );

    const relatedCards = Array.from(
        document.querySelectorAll<HTMLElement>(
            '[data-testid="template-canvas-card"]'
        )
    );
    relatedCards.forEach((card) =>
        nc.assert.truthy(
            card.className.includes('h-full'),
            'related template cards should fill their grid row evenly'
        )
    );

    if (window.innerWidth >= 1024 && sectionCards.length > 1) {
        const toc = document.querySelector('aside') as HTMLElement | null;
        nc.assert.truthy(
            toc?.querySelector('nav a[href^="#"]'),
            'long desktop template pages should keep the original slim contents rail'
        );
        nc.assert.truthy(
            Boolean(
                toc &&
                    hero &&
                    hero.getBoundingClientRect().left >=
                        toc.getBoundingClientRect().right
            ),
            'the hero canvas should sit beside the contents rail'
        );
    }

    nc.assert.equal(
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
        'the redesigned template page should not overflow horizontally'
    );

    return {
        path: window.location.pathname,
        variant: page?.dataset.templateVariant ?? 'base',
        sectionCount: sectionCards.length,
    };
}
