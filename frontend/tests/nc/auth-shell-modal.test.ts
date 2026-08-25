// Browser regression for the shared authentication modal on the landing page.
// It opens the real signup popup, checks its geometry, and exercises the sign-in mode switch without submitting auth.
import { nc } from '~/lib/nc';

export default async function () {
    nc.assert.equal(
        window.location.pathname,
        '/',
        'Open the landing page before running this test'
    );

    const signupButton = Array.from(document.querySelectorAll('button')).find(
        (button) => button.textContent?.trim() === 'Sign Up'
    ) as HTMLButtonElement | undefined;
    nc.assert.truthy(
        signupButton,
        'Landing page should expose a signup button'
    );
    signupButton!.click();

    const modal = await nc.wait.forElement('[data-testid="auth-shell-modal"]');
    nc.assert.includes(
        modal.textContent ?? '',
        'Your agent is waiting.',
        'Signup popup should use the auth headline'
    );
    nc.assert.includes(
        modal.textContent ?? '',
        'Continue with Google',
        'Signup popup should preserve Google auth'
    );
    nc.assert.includes(
        modal.textContent ?? '',
        'Continue with email',
        'Signup popup should expose email as a compact auth option'
    );
    nc.assert.includes(
        modal.textContent ?? '',
        'Enterprise SSO',
        'Signup popup should expose SSO as a primary auth option'
    );
    nc.assert.falsy(
        modal.querySelector('[data-testid="auth-modal-email-form"]'),
        'Credential fields should stay hidden on the compact option screen'
    );
    nc.assert.falsy(
        modal.querySelector('[data-testid="turnstile-widget"]'),
        'Turnstile should mount only when the email form is requested'
    );
    nc.assert.falsy(
        modal.textContent?.includes('Free to start'),
        'Signup popup should omit the utility label'
    );
    const compactBrand = modal.querySelector(
        '[data-testid="auth-shell-brand"]'
    ) as HTMLElement | null;
    const compactMark = compactBrand?.querySelector('img');
    nc.assert.truthy(
        compactMark && compactMark.getBoundingClientRect().width <= 22,
        'Modal logo mark should be smaller relative to its wordmark'
    );
    const footer = await nc.wait.forElement(
        '[data-testid="auth-modal-footer"]'
    );
    nc.assert.equal(
        getComputedStyle(footer).fontSize,
        '14px',
        'Modal footer actions should use the more visible text size'
    );
    nc.assert.truthy(
        modal.getBoundingClientRect().width <= 448,
        'Auth popup should use the compact modal width'
    );
    const modalWidth = Math.round(modal.getBoundingClientRect().width);
    const optionModalHeight = Math.round(modal.getBoundingClientRect().height);

    const ssoButton = Array.from(modal.querySelectorAll('button')).find(
        (button) => button.textContent?.trim() === 'Enterprise SSO'
    ) as HTMLButtonElement | undefined;
    nc.assert.truthy(ssoButton, 'Signup popup should offer Enterprise SSO');
    ssoButton!.click();
    await nc.wait.until(() => modal.querySelector('#modal-sso-slug') !== null);
    nc.assert.includes(
        modal.textContent ?? '',
        'Continue with SSO',
        'SSO choice should open the existing organization flow'
    );
    const backToOptions = Array.from(modal.querySelectorAll('button')).find(
        (button) => button.textContent?.trim() === '← Back to options'
    ) as HTMLButtonElement | undefined;
    nc.assert.truthy(backToOptions, 'SSO flow should return to auth options');
    backToOptions!.click();
    await nc.wait.until(
        () => modal.querySelector('[data-testid="auth-modal-options"]') !== null
    );

    const emailButton = Array.from(modal.querySelectorAll('button')).find(
        (button) => button.textContent?.trim() === 'Continue with email'
    ) as HTMLButtonElement | undefined;
    nc.assert.truthy(emailButton, 'Signup popup should offer email auth');
    emailButton!.click();
    const emailForm = await nc.wait.forElement(
        '[data-testid="auth-modal-email-form"]'
    );
    nc.assert.truthy(
        emailForm.querySelector('input[name="email"]'),
        'Email choice should reveal the existing credential form'
    );
    nc.assert.truthy(
        modal.querySelector('[data-testid="turnstile-widget"]'),
        'Email form should preserve interaction-only Turnstile protection'
    );

    const signInButton = Array.from(modal.querySelectorAll('button')).find(
        (button) => button.textContent?.trim() === 'Sign in'
    ) as HTMLButtonElement | undefined;
    nc.assert.truthy(signInButton, 'Signup popup should offer sign-in mode');
    signInButton!.click();
    await nc.wait.until(
        () => modal.textContent?.includes('Welcome back.') === true
    );
    nc.assert.truthy(
        modal.querySelector('input[name="email"]'),
        'Mode switch should keep the sign-in form mounted'
    );
    const exactSignInLabels = Array.from(modal.querySelectorAll('*')).filter(
        (element) =>
            element.children.length === 0 &&
            element.textContent?.trim() === 'Sign in'
    );
    nc.assert.equal(
        exactSignInLabels.length,
        1,
        'Sign-in modal should only show the primary action label'
    );
    nc.assert.truthy(
        modal.querySelector('button[aria-label="Close authentication"]'),
        'Auth popup should include an accessible close control'
    );

    const closeButton = modal.querySelector(
        'button[aria-label="Close authentication"]'
    ) as HTMLButtonElement;
    closeButton.click();
    await nc.wait.until(
        () =>
            document.querySelector('[data-testid="auth-shell-modal"]') === null
    );

    nc.assert.truthy(
        document.documentElement.scrollWidth <=
            document.documentElement.clientWidth,
        'Production auth modal should not create horizontal overflow'
    );

    return { modalWidth, optionModalHeight };
}
