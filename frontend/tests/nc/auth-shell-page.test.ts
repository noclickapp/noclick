// Browser regression for the production Auth register and login pages.
// It verifies the open-form composition, real auth controls, and unchanged desktop right-panel geometry.
import { nc } from '~/lib/nc';

export default async function () {
    const isRegister = window.location.pathname === '/auth/register';
    nc.assert.truthy(
        isRegister || window.location.pathname === '/auth/login',
        'Open /auth/register or /auth/login before running this test'
    );

    const page = await nc.wait.forElement('[data-testid="auth-shell-page"]');
    const form = await nc.wait.forElement('[data-testid="auth-shell-form"]');
    const leftPanel = await nc.wait.forElement(
        '[data-testid="auth-left-panel"]'
    );
    const brand = await nc.wait.forElement('[data-testid="auth-shell-brand"]');
    const turnstile = await nc.wait.forElement(
        '[data-testid="turnstile-widget"]'
    );
    const rightPanel = document.querySelector(
        '[data-testid="auth-right-panel"]'
    ) as HTMLElement | null;

    nc.assert.includes(
        page.textContent ?? '',
        isRegister ? 'Build an agent.' : 'Welcome back.',
        'Auth page should use its auth headline'
    );
    nc.assert.includes(
        page.textContent ?? '',
        isRegister ? 'Then let it run.' : 'Welcome back.',
        'Auth page should preserve its primary Auth copy'
    );
    if (!isRegister) {
        nc.assert.falsy(
            page.textContent?.includes('Account / 02'),
            'Login page should omit the account eyebrow'
        );
        nc.assert.falsy(
            page.textContent?.includes('Your agents kept running.'),
            'Login page should omit the oversized secondary headline'
        );
    }

    const controls = [
        'input[name="email"]',
        'input[name="password"]',
        'button[type="submit"]',
    ];
    if (isRegister) controls.push('input[name="confirmPassword"]');

    for (const control of controls) {
        nc.assert.truthy(
            form.querySelector(control),
            `Register page should preserve ${control}`
        );
    }

    nc.assert.includes(
        form.textContent ?? '',
        'Continue with Google',
        'Register page should preserve Google auth'
    );
    nc.assert.equal(
        getComputedStyle(form).borderTopWidth,
        '0px',
        'Auth form should remain open instead of becoming a card'
    );
    nc.assert.truthy(
        form.getBoundingClientRect().width <= 448,
        'Auth form should keep a realistic auth width'
    );
    const brandMark = brand.querySelector('img') as HTMLImageElement | null;
    nc.assert.truthy(
        brandMark && brandMark.getBoundingClientRect().width <= 28,
        'Page-level Auth logo should keep its reduced size'
    );
    const submitButton = form.querySelector(
        'button[type="submit"]'
    ) as HTMLButtonElement;
    await nc.wait.until(() => !submitButton.disabled, 10_000);
    nc.assert.truthy(
        turnstile.getBoundingClientRect().height <= 1,
        'Solved interaction-only Turnstile should collapse without visible chrome'
    );

    if (window.innerWidth >= 1024) {
        nc.assert.truthy(
            rightPanel && getComputedStyle(rightPanel).display !== 'none',
            'Desktop register page should preserve the right panel'
        );
        nc.assert.truthy(
            rightPanel?.querySelector(
                'img[alt="Black hole visualization"], video[aria-label="Slowly rotating black hole visualization"]'
            ),
            'Desktop register page should preserve the black-hole artwork'
        );
        nc.assert.truthy(
            rightPanel && rightPanel.getBoundingClientRect().width > 400,
            'Desktop right panel should keep its product-scale width'
        );
        nc.assert.truthy(
            leftPanel.getBoundingClientRect().width >
                form.getBoundingClientRect().width,
            'Left panel should frame the form without stretching it'
        );
    }

    nc.assert.truthy(
        document.documentElement.scrollWidth <=
            document.documentElement.clientWidth,
        'Production auth page should not create horizontal overflow'
    );

    return {
        path: window.location.pathname,
        formWidth: Math.round(form.getBoundingClientRect().width),
        rightPanelWidth: rightPanel
            ? Math.round(rightPanel.getBoundingClientRect().width)
            : 0,
    };
}
