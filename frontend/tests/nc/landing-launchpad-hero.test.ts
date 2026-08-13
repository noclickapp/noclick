import { nc } from '~/lib/nc';

const testIds = {
    planes: [
        'space-hero-galaxy-plane-halo',
        'space-hero-galaxy-plane-depth',
        'space-hero-galaxy-plane-main',
        'space-hero-galaxy-plane-core',
    ],
    spinners: [
        'space-hero-galaxy-spinner-halo',
        'space-hero-galaxy-spinner-depth',
        'space-hero-galaxy-spinner-main',
        'space-hero-galaxy-spinner-core',
    ],
    textures: [
        'space-hero-galaxy-texture-halo',
        'space-hero-galaxy-texture-depth',
        'space-hero-galaxy-texture-main',
        'space-hero-galaxy-texture-core',
    ],
};

export default async function () {
    nc.assert.equal(
        window.location.pathname,
        '/',
        'Open the landing page before running this test'
    );

    const hero = await nc.wait.forElement('[data-testid="launchpad-hero"]');
    const spaceHero = hero.querySelector(
        '[data-testid="space-hero"]'
    ) as HTMLElement;
    const art = spaceHero.querySelector(
        '[data-testid="space-hero-art"]'
    ) as HTMLElement;
    await nc.wait.forElement('[data-testid="space-hero-art"][data-ready="true"]');
    const content = spaceHero.querySelector(
        '.space-hero__content'
    ) as HTMLElement;
    const heading = content.querySelector('h1') as HTMLElement;
    const primaryTitle = heading.querySelector(
        '[data-testid="space-hero-title-primary"]'
    ) as HTMLElement;
    const secondaryTitle = heading.querySelector(
        '[data-testid="space-hero-title-secondary"]'
    ) as HTMLElement;
    const supportingCopy = content.querySelector(
        '[data-testid="space-hero-supporting-copy"]'
    ) as HTMLElement;
    const heroActions = content.querySelector(
        '[data-testid="launchpad-hero-actions"]'
    ) as HTMLElement;
    const camera = art.querySelector(
        '[data-testid="space-hero-galaxy-camera"]'
    ) as HTMLElement;
    const rig = art.querySelector(
        '[data-testid="space-hero-galaxy-rig"]'
    ) as HTMLElement;
    const planes = testIds.planes.map(
        (testId) =>
            art.querySelector(`[data-testid="${testId}"]`) as HTMLElement
    );
    const spinners = testIds.spinners.map(
        (testId) =>
            art.querySelector(`[data-testid="${testId}"]`) as HTMLElement
    );
    const textures = testIds.textures.map(
        (testId) =>
            art.querySelector(`[data-testid="${testId}"]`) as HTMLImageElement
    );
    const haze = art.querySelector(
        '[data-testid="space-hero-galaxy-haze"]'
    ) as HTMLElement;
    const depthLight = art.querySelector(
        '[data-testid="space-hero-galaxy-depth-light"]'
    ) as HTMLElement;
    const coreShadow = art.querySelector(
        '[data-testid="space-hero-galaxy-core-shadow"]'
    ) as HTMLElement;
    const bulge = art.querySelector(
        '[data-testid="space-hero-galaxy-bulge"]'
    ) as HTMLElement;
    const bulgeBase = art.querySelector(
        '[data-testid="space-hero-galaxy-bulge-base"]'
    ) as HTMLElement;

    nc.assert.equal(
        Array.from(heading.children)
            .map((line) => line.textContent?.trim())
            .join(' '),
        'AI agents for background tasks',
        'Layered hero should preserve the approved headline'
    );
    nc.assert.truthy(
        getComputedStyle(heading).fontFamily.includes('Outfit'),
        'Hero should preserve the brand display font'
    );
    nc.assert.equal(
        primaryTitle.textContent?.trim(),
        'AI agents for',
        'Primary title line should use the templates-page editorial split'
    );
    nc.assert.equal(
        secondaryTitle.textContent?.trim(),
        'background tasks',
        'Secondary title line should use the templates-page editorial split'
    );
    nc.assert.falsy(
        Array.from(content.querySelectorAll('*')).some(
            (element) =>
                element.textContent?.trim() ===
                'The agentic layer for your business'
        ),
        'Hero should not render the removed eyebrow copy'
    );
    nc.assert.truthy(
        parseFloat(getComputedStyle(primaryTitle).paddingBottom) > 0 &&
            parseFloat(getComputedStyle(secondaryTitle).paddingBottom) > 0,
        'Both gradient title lines should leave room for font descenders'
    );
    nc.assert.equal(
        supportingCopy.textContent?.replace(/\s+/g, ' ').trim(),
        'Bring your ChatGPT or Claude subscription, or use your own API keys. Describe the task once. NoClick builds an agent that takes care of it every time.',
        'Hero copy should explain subscription support and the recurring outcome'
    );
    nc.assert.truthy(
        parseFloat(getComputedStyle(supportingCopy).fontSize) >= 18 &&
            Number(getComputedStyle(supportingCopy).fontWeight) >= 500,
        'Hero copy should remain substantial and readable'
    );
    nc.assert.truthy(
        (heroActions.textContent ?? '').includes('Start Free'),
        'Hero should preserve the primary CTA'
    );
    nc.assert.truthy(
        (heroActions.textContent ?? '').includes('Book Demo'),
        'Hero should preserve the demo CTA'
    );
    nc.assert.truthy(
        heroActions.getBoundingClientRect().top >=
            heading.getBoundingClientRect().bottom,
        'Hero CTAs should sit below the title'
    );
    const footer = document.querySelector('footer') as HTMLElement;
    nc.assert.truthy(
        (footer?.textContent ?? '')
            .replace(/\s+/g, ' ')
            .includes('Set it up once. It keeps getting done.'),
        'Footer promise should distinguish recurring agents from one-off chats'
    );
    const primaryCta = heroActions.querySelector(
        '#hero-cta'
    ) as HTMLButtonElement;
    nc.assert.falsy(
        primaryCta.className.includes('hover:-translate-y'),
        'Primary CTA should stay fixed in place on hover'
    );
    nc.assert.truthy(
        primaryCta
            .querySelector('svg')
            ?.getAttribute('class')
            ?.includes('group-hover:translate-x-0.5'),
        'Primary CTA should use the footer-style in-place arrow motion'
    );

    nc.assert.equal(
        art.getAttribute('aria-hidden'),
        'true',
        'Decorative artwork should be hidden from assistive technology'
    );
    nc.assert.equal(
        getComputedStyle(art).pointerEvents,
        'none',
        'Artwork should never intercept CTA or prompt input'
    );
    nc.assert.equal(
        art.querySelectorAll('.space-hero__background').length,
        0,
        'Pure-black hero should not request a background image'
    );
    nc.assert.equal(
        spaceHero.querySelectorAll(
            '[data-testid="space-hero-background-picker"], [data-testid="space-hero-motion-control"]'
        ).length,
        0,
        'Final hero should not render comparison or motion controls'
    );

    const expectedAssets = [
        '/space-hero/galaxy-halo-parallax.png',
        '/space-hero/galaxy-depth-parallax.png',
        '/space-hero/galaxy-main-parallax.png',
        '/space-hero/galaxy-core-parallax.png',
    ];
    const expectedOptimizedAssets = expectedAssets.map((src) =>
        src.replace('.png', '.webp')
    );
    textures.forEach((texture, index) => {
        nc.assert.equal(texture.alt, '', 'Galaxy layers should be decorative');
        nc.assert.equal(
            texture.getAttribute('src'),
            expectedAssets[index],
            'Each galaxy layer should retain a transparent PNG fallback'
        );
        nc.assert.equal(
            texture.parentElement
                ?.querySelector('source')
                ?.getAttribute('srcset'),
            expectedOptimizedAssets[index],
            'Each galaxy layer should offer a lossless WebP source'
        );
        nc.assert.equal(
            texture.getAttribute('width'),
            '1254',
            'Galaxy layer width should be explicit'
        );
        nc.assert.equal(
            texture.getAttribute('height'),
            '1254',
            'Galaxy layer height should be explicit'
        );
        nc.assert.equal(
            getComputedStyle(texture).objectFit,
            'contain',
            'Galaxy textures should never be cropped with object-fit cover'
        );
        nc.assert.falsy(
            getComputedStyle(texture).filter.includes('blur'),
            'Galaxy texture grain should not be softened by CSS blur'
        );
        nc.assert.truthy(
            getComputedStyle(texture).transitionProperty.includes('opacity'),
            'Decoded galaxy layers should reveal together with a graceful fade'
        );
    });

    nc.assert.equal(
        art.querySelectorAll(
            '[data-testid="space-hero-galaxy-volume-shell"], [data-testid="space-hero-galaxy-dust-shelf"]'
        ).length,
        0,
        'Detached screen-space galaxy strips should not be rendered'
    );
    for (const edgeSafeLeaf of [haze, depthLight]) {
        nc.assert.truthy(
            getComputedStyle(edgeSafeLeaf).maskImage !== 'none',
            'Atmosphere and lighting leaves should fade before their rectangular bounds'
        );
    }

    const heroStyle = getComputedStyle(spaceHero);
    const cameraStyle = getComputedStyle(camera);
    const rigStyle = getComputedStyle(rig);
    const contentStyle = getComputedStyle(content);
    const expectedPerspective =
        window.innerWidth <= 700
            ? '780px'
            : window.innerWidth <= 1100
              ? '920px'
              : '1050px';

    nc.assert.equal(
        heroStyle.backgroundColor,
        'rgb(0, 0, 0)',
        'Space scene should use true black'
    );
    nc.assert.equal(
        cameraStyle.perspective,
        expectedPerspective,
        'Camera should provide real perspective instead of a 2D squash'
    );
    nc.assert.truthy(
        rigStyle.transform !== 'none',
        'Rig should own fixed placement and screen orientation'
    );
    nc.assert.equal(
        cameraStyle.transformStyle,
        'preserve-3d',
        'Camera should preserve the 3D context'
    );
    nc.assert.equal(
        rigStyle.transformStyle,
        'preserve-3d',
        'Rig should preserve the 3D context'
    );
    planes.forEach((plane) => {
        const planeStyle = getComputedStyle(plane);
        nc.assert.equal(
            planeStyle.transformStyle,
            'preserve-3d',
            'Every tilted galaxy plane should preserve the 3D context'
        );
        nc.assert.falsy(
            new DOMMatrix(planeStyle.transform).is2D,
            'Every galaxy plane should use rotateX, rotateY, and translateZ'
        );
    });
    nc.assert.equal(
        [
            '--galaxy-depth-halo',
            '--galaxy-depth-dust',
            '--galaxy-depth-main',
            '--galaxy-depth-core',
        ]
            .map((property) => heroStyle.getPropertyValue(property).trim())
            .join(','),
        (window.innerWidth <= 700
            ? ['-24px', '-10px', '0px', '14px']
            : ['-34px', '-14px', '0px', '18px']
        ).join(','),
        'Galaxy textures should occupy distinct Z planes for real parallax'
    );

    for (const intermediate of [camera, rig, ...planes]) {
        const style = getComputedStyle(intermediate);
        nc.assert.equal(
            style.opacity,
            '1',
            '3D intermediate wrappers must not use opacity'
        );
        nc.assert.equal(
            style.filter,
            'none',
            '3D intermediate wrappers must not use filters'
        );
        nc.assert.equal(
            style.overflow,
            'visible',
            '3D intermediate wrappers must not clip their children'
        );
        nc.assert.equal(
            style.clipPath,
            'none',
            '3D intermediate wrappers must not use clip-path'
        );
        nc.assert.equal(
            style.maskImage,
            'none',
            '3D intermediate wrappers must not use masks'
        );
        nc.assert.equal(
            style.mixBlendMode,
            'normal',
            '3D intermediate wrappers must not flatten through blending'
        );
    }

    nc.assert.equal(
        art.querySelectorAll('[data-testid="space-hero-foreground"]').length,
        0,
        'The scene should follow the explicit no-foreground direction'
    );
    nc.assert.equal(
        art.querySelectorAll('video, canvas').length,
        0,
        'Layered hero should use neither video nor canvas'
    );

    const expectedDurations = ['330s', '315s', '300s', '288s'];
    spinners.forEach((spinner, index) => {
        const style = getComputedStyle(spinner);
        nc.assert.equal(
            style.animationName,
            'space-hero-galaxy-spin',
            'Only local galaxy textures should use the rotation keyframes'
        );
        nc.assert.equal(
            style.animationDuration,
            expectedDurations[index],
            'Each galaxy plate should use its deliberately slow duration'
        );
        nc.assert.equal(
            style.animationTimingFunction,
            'linear',
            'Galaxy rotation should remain perfectly linear'
        );
        nc.assert.equal(
            style.animationIterationCount,
            'infinite',
            'Galaxy rotation should loop continuously'
        );
        nc.assert.equal(
            style.animationPlayState,
            'running',
            'Galaxy should always rotate without requiring a control'
        );
    });

    const mainAnimation = spinners[2].getAnimations()[0];
    mainAnimation.pause();
    mainAnimation.currentTime = 0;
    const firstTransform = getComputedStyle(spinners[2]).transform;
    mainAnimation.currentTime = 5_000;
    const secondTransform = getComputedStyle(spinners[2]).transform;
    nc.assert.truthy(
        firstTransform !== secondTransform,
        'Always-on galaxy keyframes should produce a changing transform'
    );
    mainAnimation.play();
    for (const fixedLayer of [
        camera,
        rig,
        haze,
        depthLight,
        coreShadow,
        bulgeBase,
        bulge,
    ]) {
        nc.assert.equal(
            getComputedStyle(fixedLayer).animationName,
            'none',
            'Camera, rig, tilt, lighting, atmosphere, and bulge must remain fixed'
        );
    }

    nc.assert.equal(
        cameraStyle.zIndex,
        '1',
        'Galaxy rig should sit above the pure-black background'
    );
    nc.assert.equal(
        contentStyle.zIndex,
        '4',
        'Hero content should remain above all artwork'
    );

    const promptSection = hero.querySelector(
        '[data-testid="launchpad-prompt-section"]'
    ) as HTMLElement;
    const promptShowcase = promptSection.querySelector(
        '[data-testid="hero-prompt-showcase"]'
    ) as HTMLElement;
    const heroRect = spaceHero.getBoundingClientRect();
    const promptRect = promptSection.getBoundingClientRect();
    nc.assert.truthy(
        promptRect.top >= heroRect.bottom - 1,
        'Launchpad prompt should begin after the complete layered artwork'
    );
    nc.assert.truthy(
        promptShowcase,
        'Real prompt component should remain mounted'
    );
    nc.assert.truthy(
        document.documentElement.scrollWidth <=
            document.documentElement.clientWidth,
        'Oversized 3D artwork should not create horizontal page overflow'
    );

    const workflowMode = promptShowcase.querySelector(
        'button[aria-pressed="true"]'
    ) as HTMLButtonElement;
    nc.assert.equal(
        workflowMode.textContent?.trim(),
        'Workflow',
        'Workflow should remain the default prompt mode'
    );
    const interfaceMode = Array.from(
        promptShowcase.querySelectorAll('button')
    ).find((button) => button.textContent?.trim() === 'Interface') as
        | HTMLButtonElement
        | undefined;
    nc.assert.truthy(interfaceMode, 'Interface mode should remain available');

    const transformLayers = Array.from(spaceHero.querySelectorAll('*')).filter(
        (element) => getComputedStyle(element).willChange === 'transform'
    );
    nc.assert.equal(
        transformLayers.length,
        4,
        'Only the four rotating galaxy textures should reserve compositor layers'
    );

    return {
        headline: heading.textContent?.trim(),
        durations: expectedDurations,
        galaxy: {
            x: heroStyle.getPropertyValue('--galaxy-x').trim(),
            y: heroStyle.getPropertyValue('--galaxy-y').trim(),
            size: heroStyle.getPropertyValue('--galaxy-size').trim(),
            perspective: heroStyle
                .getPropertyValue('--galaxy-perspective')
                .trim(),
            tilt: heroStyle.getPropertyValue('--galaxy-tilt').trim(),
            yaw: heroStyle.getPropertyValue('--galaxy-yaw').trim(),
        },
        alwaysRotating: true,
    };
}
