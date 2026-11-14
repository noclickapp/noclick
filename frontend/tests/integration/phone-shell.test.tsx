// The phone shell in a real browser with an iPhone's notch and home indicator: a page's foot (its message box) sits
// clear of the indicator and its top under the notch, with no room kept by the page itself, so every page's box is where
// a thumb reaches it.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { cdp, page } from 'vitest/browser';
import { afterEach, expect, it } from 'vitest';
import { AppShell } from '~/components/shell/AppShell';

const NOTCH = 47;
const HOME_INDICATOR = 34;

let unmount: (() => void) | null = null;
afterEach(async () => {
    unmount?.();
    unmount = null;
    await cdp().send('Emulation.setSafeAreaInsetsOverride', { insets: { top: 0, topMax: 0, bottom: 0, bottomMax: 0, left: 0, right: 0 } });
    document.querySelector('meta[name=viewport][data-test]')?.remove();
});

it('keeps a page’s foot clear of the home indicator and its top under the notch', async () => {
    await page.viewport(390, 844);
    const meta = document.createElement('meta');
    meta.name = 'viewport';
    meta.content = 'width=device-width, initial-scale=1, viewport-fit=cover';
    meta.dataset.test = '';
    document.head.appendChild(meta);
    await cdp().send('Emulation.setSafeAreaInsetsOverride', { insets: { top: NOTCH, topMax: NOTCH, bottom: HOME_INDICATOR, bottomMax: HOME_INDICATOR, left: 0, right: 0 } });

    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    flushSync(() =>
        root.render(
            <AppShell
                isMobile
                sidebar={{ user: { email: 'dhruv@example.com' }, selectedTab: 'chat', onTabChange: () => undefined }}
                collapsed={false}
                onCollapsedChange={() => undefined}
                title=""
                builder={null}
                builderShown={false}
                builderWidth={0}
                animate={false}
            >
                <div className="flex h-full flex-col justify-end">
                    <button type="button">Send</button>
                </div>
            </AppShell>
        )
    );
    unmount = () => {
        flushSync(() => root.unmount());
        host.remove();
    };

    const box = [...document.querySelectorAll('button')].find((b) => b.textContent === 'Send')!.getBoundingClientRect();
    expect(box.bottom, 'The page’s foot sits clear of the home indicator').toBeLessThanOrEqual(window.innerHeight - HOME_INDICATOR);
    expect(box.bottom, 'right on it, with no gap of its own').toBeGreaterThan(window.innerHeight - HOME_INDICATOR - 2);
    const menu = document.querySelector('[aria-label="Open menu"]')!.getBoundingClientRect();
    expect(menu.top, 'The bar sits under the notch').toBeGreaterThanOrEqual(NOTCH);
});
