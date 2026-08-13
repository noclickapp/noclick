import { nc } from '~/lib/nc';

interface ViewportExpectation {
    width: number;
    height: number;
    x: string;
    y: string;
    size: string;
    perspective: string;
    tilt: string;
    yaw: string;
    angle: string;
}

const viewports: ViewportExpectation[] = [
    {
        width: 1920,
        height: 1080,
        x: '66%',
        y: '59%',
        size: 'min(104vw, 1660px)',
        perspective: '1050px',
        tilt: '75deg',
        yaw: '-5deg',
        angle: '-9deg',
    },
    {
        width: 1440,
        height: 900,
        x: '66%',
        y: '59%',
        size: 'min(104vw, 1660px)',
        perspective: '1050px',
        tilt: '75deg',
        yaw: '-5deg',
        angle: '-9deg',
    },
    {
        width: 1280,
        height: 800,
        x: '66%',
        y: '59%',
        size: 'min(104vw, 1660px)',
        perspective: '1050px',
        tilt: '75deg',
        yaw: '-5deg',
        angle: '-9deg',
    },
    {
        width: 768,
        height: 1024,
        x: '67%',
        y: '63%',
        size: 'min(162vw, 1390px)',
        perspective: '920px',
        tilt: '75deg',
        yaw: '-5deg',
        angle: '-9deg',
    },
    {
        width: 390,
        height: 844,
        x: '70%',
        y: '63%',
        size: '208vw',
        perspective: '780px',
        tilt: '74deg',
        yaw: '-4deg',
        angle: '-10deg',
    },
];

function waitForFrame(frame: HTMLIFrameElement) {
    return new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(
            () => reject(new Error('Responsive hero frame did not load')),
            15_000
        );

        frame.addEventListener(
            'load',
            () => {
                window.clearTimeout(timeout);
                window.setTimeout(resolve, 250);
            },
            { once: true }
        );
    });
}

export default async function () {
    if (
        window.location.pathname !== '/' ||
        new URLSearchParams(window.location.search).has('space-hero-viewport')
    ) {
        return { helperFrame: true };
    }

    nc.assert.equal(
        window.location.pathname,
        '/',
        'Open the landing page before running this test'
    );

    const results = [];

    for (const viewport of viewports) {
        const frame = document.createElement('iframe');
        frame.setAttribute('aria-hidden', 'true');
        frame.style.position = 'fixed';
        frame.style.top = '0';
        frame.style.left = '0';
        frame.style.width = `${viewport.width}px`;
        frame.style.height = `${viewport.height}px`;
        frame.style.border = '0';
        frame.style.opacity = '0';
        frame.style.pointerEvents = 'none';
        document.body.appendChild(frame);

        const loaded = waitForFrame(frame);
        frame.src = `/?space-hero-viewport=${viewport.width}x${viewport.height}`;
        await loaded;

        const frameWindow = frame.contentWindow;
        const frameDocument = frame.contentDocument;
        nc.assert.truthy(
            frameWindow && frameDocument,
            'Responsive test frame should be same-origin'
        );

        const hero = frameDocument!.querySelector(
            '[data-testid="space-hero"]'
        ) as HTMLElement;
        const heading = hero.querySelector('h1') as HTMLElement;
        const secondaryTitle = hero.querySelector(
            '[data-testid="space-hero-title-secondary"]'
        ) as HTMLElement;
        const actions = hero.querySelector(
            '[data-testid="launchpad-hero-actions"]'
        ) as HTMLElement;
        const camera = hero.querySelector(
            '[data-testid="space-hero-galaxy-camera"]'
        ) as HTMLElement;
        const rig = hero.querySelector(
            '[data-testid="space-hero-galaxy-rig"]'
        ) as HTMLElement;
        const mainTexture = hero.querySelector(
            '[data-testid="space-hero-galaxy-texture-main"]'
        ) as HTMLImageElement;
        const heroStyle = frameWindow!.getComputedStyle(hero);
        const headingRect = heading.getBoundingClientRect();
        const actionsRect = actions.getBoundingClientRect();
        const heroRect = hero.getBoundingClientRect();

        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-x').trim(),
            viewport.x,
            'Responsive galaxy x position should match its tuned value'
        );
        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-y').trim(),
            viewport.y,
            'Responsive galaxy y position should match its tuned value'
        );
        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-size').trim(),
            viewport.size,
            'Responsive galaxy size should match its tuned value'
        );
        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-perspective').trim(),
            viewport.perspective,
            'Responsive camera perspective should match its tuned value'
        );
        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-tilt').trim(),
            viewport.tilt,
            'Responsive plane tilt should match its tuned value'
        );
        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-yaw').trim(),
            viewport.yaw,
            'Responsive plane yaw should match its tuned value'
        );
        nc.assert.equal(
            heroStyle.getPropertyValue('--galaxy-screen-angle').trim(),
            viewport.angle,
            'Responsive screen angle should match its tuned value'
        );
        nc.assert.equal(
            frameWindow!.getComputedStyle(camera).perspective,
            viewport.perspective,
            'The CSS camera should resolve to the intended perspective'
        );
        nc.assert.truthy(
            headingRect.left >= 0 && headingRect.right <= viewport.width,
            'Hero title should remain inside the viewport'
        );
        nc.assert.truthy(
            actionsRect.left >= 0 && actionsRect.right <= viewport.width,
            'Hero CTAs should remain inside the viewport'
        );
        nc.assert.truthy(
            headingRect.bottom < heroRect.height * 0.52,
            'Title should stay in the quiet upper half of the hero'
        );
        nc.assert.truthy(
            parseFloat(
                frameWindow!.getComputedStyle(secondaryTitle).paddingBottom
            ) > 0,
            'Descenders should retain explicit breathing room'
        );
        nc.assert.equal(
            frameWindow!.getComputedStyle(rig).overflow,
            'visible',
            'The 3D rig should remain unflattened at every breakpoint'
        );
        nc.assert.equal(
            mainTexture.naturalWidth,
            1254,
            'The full-resolution main galaxy should load'
        );
        nc.assert.truthy(
            frameDocument!.documentElement.scrollWidth <= viewport.width,
            'Artwork should not produce horizontal page overflow'
        );

        results.push({
            viewport: `${viewport.width}x${viewport.height}`,
            heroHeight: Math.round(heroRect.height),
            titleBottom: Math.round(headingRect.bottom),
            noOverflow:
                frameDocument!.documentElement.scrollWidth <= viewport.width,
        });

        frame.remove();
    }

    localStorage.setItem(
        'nc-space-hero-responsive-results',
        JSON.stringify(results)
    );
    return results;
}
