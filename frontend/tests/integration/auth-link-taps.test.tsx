// The sign-in pages' text links on a phone, in a real browser: each answers a tap anywhere within a fingertip (40px)
// of its words, though it looks no taller than its line of text.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { createMemoryRouter, Link, RouterProvider } from 'react-router';
import { page } from 'vitest/browser';
import { afterEach, expect, it } from 'vitest';
import { AuthPageHeader } from '~/components/auth/AuthPageHeader';
import { AUTH_LINK_CLASS, AUTH_QUIET_LINK_CLASS } from '~/components/auth/authStyle';
import { cn } from '~/lib/utils';

let unmount: (() => void) | null = null;
afterEach(() => {
    unmount?.();
    unmount = null;
});

it('gives each text link a fingertip’s tap around its words', async () => {
    await page.viewport(390, 844);
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;inset:0;padding:24px';
    document.body.appendChild(host);
    const root = createRoot(host);
    const screen = (
        <div>
            <AuthPageHeader back={{ to: '/auth/login', label: 'Back to sign in' }} title="Reset your password" description="We'll email you a link." />
            <p className="mt-10 flex gap-4 text-[13px]">
                <Link to="/auth/register" className={AUTH_LINK_CLASS}>
                    Create account
                </Link>
                <Link to="/auth/forgot-password" className={cn('text-[13px]', AUTH_QUIET_LINK_CLASS)}>
                    Forgot password?
                </Link>
            </p>
        </div>
    );
    const router = createMemoryRouter([{ path: '/', element: screen }]);
    flushSync(() => root.render(<RouterProvider router={router} />));
    unmount = () => {
        flushSync(() => root.unmount());
        host.remove();
    };

    for (const name of ['Back to sign in', 'Create account', 'Forgot password?']) {
        const link = [...host.querySelectorAll('a')].find((a) => a.textContent?.includes(name))!;
        const r = link.getBoundingClientRect();
        expect(r.height, `${name} looks no taller than its text`).toBeLessThan(28);
        const x = r.left + r.width / 2;
        const middle = r.top + r.height / 2;
        for (const y of [middle - 19, middle + 19]) {
            const hit = document.elementFromPoint(x, y);
            expect(hit && link.contains(hit), `${name} takes a tap ${Math.round(Math.abs(y - middle))}px from its middle`).toBe(true);
        }
    }
}, 30_000);
