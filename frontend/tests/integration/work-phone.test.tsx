// Work on a phone, in a real browser: at an iPhone's width and a small Android's, in both themes, nothing scrolls
// sideways; each list's top (the space's mark, its action card, its search) starts on the 16px edge its rows' faces
// start on, and everything in it takes a finger (40px); every Resources kind page gives its title and the line under it
// the page's width, its buttons on a row of their own inside the page; with an iPhone's home indicator, a channel's or
// a DM's composer stays clear of it; and the Resources list's Overview opens. Each screen is a screenshot under
// __screenshots__ (git-ignored), for a person to see.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { useState, type ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { cdp, page } from 'vitest/browser';
import { afterEach, expect, it } from 'vitest';
import { PhoneBarSlotProvider } from '~/components/shell/AppShell';
import { WorkClientContext } from '~/cloud/components/work/client';
import { fakeWork } from '~/cloud/components/work/fixtures/workApi';
import { WorkLiveContext } from '~/cloud/components/work/live';
import { SPACE_KINDS } from '~/cloud/components/work/resources/space/data';
import { AutomationsContext, Work } from '~/cloud/components/work/Work';

const USER = { email: 'dhruv@example.com', display_name: 'Dhruv Yadav' };
const NO_AUTOMATIONS = { list: async () => [], add: async () => undefined };
const PHONES = [
    [390, 844],
    [360, 740],
] as const;
/** The screen's side gutter, where every list's content starts. */
const EDGE = 16;
/** A finger's tap. */
const TAP = 40;
/** An iPhone's home indicator: the strip at the screen's foot a thumb can't use. */
const HOME_INDICATOR = 34;

let unmount: (() => void) | null = null;
afterEach(() => {
    unmount?.();
    unmount = null;
    localStorage.clear();
    document.documentElement.classList.add('dark');
});

/** The phone shell's bar, as the app draws it. */
function PhoneBar({ children }: { children: ReactNode }) {
    const [slot, setSlot] = useState<HTMLElement | null>(null);
    const [lead, setLead] = useState<HTMLElement | null>(null);
    return (
        <>
            <div ref={setLead} />
            <div ref={setSlot} />
            <PhoneBarSlotProvider slot={slot} lead={lead} setLeadTaken={() => undefined}>
                {children}
            </PhoneBarSlotProvider>
        </>
    );
}

const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
async function until<T>(what: () => T | null | undefined | false, message: string, timeout = 8000): Promise<T> {
    const end = Date.now() + timeout;
    for (;;) {
        const got = what();
        if (got) return got;
        if (Date.now() > end) throw new Error(message);
        await wait(50);
    }
}

/** Work in the NoClick space at `query`, at a phone's size, in a theme. */
async function openWork(query: string, [width, height]: readonly [number, number], theme: 'dark' | 'light') {
    await page.viewport(width, height);
    document.documentElement.classList.toggle('dark', theme === 'dark');
    const fake = fakeWork();
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;inset:0;display:flex;flex-direction:column;z-index:30;background:hsl(var(--background))';
    document.body.appendChild(host);
    const root = createRoot(host);
    const work = (
        <WorkClientContext.Provider value={fake.client}>
            <WorkLiveContext.Provider value={fake.live}>
                <AutomationsContext.Provider value={NO_AUTOMATIONS}>
                    <Work user={USER} />
                </AutomationsContext.Provider>
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    const router = createMemoryRouter([{ path: '/dashboard', element: <PhoneBar>{work}</PhoneBar> }], { initialEntries: [`/dashboard?tab=work&space=ws_noclick${query}`] });
    flushSync(() => root.render(<RouterProvider router={router} />));
    unmount = () => {
        flushSync(() => root.unmount());
        host.remove();
    };
    return host;
}

/** The whole window as a screenshot sees it (the page's own body has no box here, its views all fixed). */
async function shot(path: string) {
    const frame = document.createElement('div');
    frame.style.cssText = 'position:fixed;inset:0;pointer-events:none';
    document.body.appendChild(frame);
    try {
        await page.screenshot({ path, element: frame });
    } finally {
        frame.remove();
    }
}

/** Nothing on the page scrolls sideways: not the document, and nothing in it past the screen's edge. */
function expectNoSidewaysScroll(host: HTMLElement, where: string) {
    expect(document.documentElement.scrollWidth, `${where}: the page scrolls sideways`).toBeLessThanOrEqual(window.innerWidth);
    expect(host.scrollWidth, `${where}: something reaches past the screen`).toBeLessThanOrEqual(host.clientWidth);
}

const left = (el: Element) => Math.round(el.getBoundingClientRect().left);

const LISTS = [
    ['Home', '', () => [...document.querySelectorAll('button')].find((b) => b.textContent?.includes('Find a conversation'))],
    ['Agents', '&show=agents', () => document.querySelector('label:has(> input[placeholder="Find an agent"])')],
    ['DMs', '&show=dms', () => document.querySelector('label:has(> input[placeholder="Find a person"])')],
] as const;

for (const size of PHONES) {
    for (const theme of ['dark', 'light'] as const) {
        for (const [view, query, search] of LISTS) {
            it(`lines ${view}’s top up with its rows at ${size[0]}px, ${theme}`, async () => {
                const host = await openWork(query, size, theme);
                const face = await until(() => document.querySelector('li > button > :first-child'), `${view} lists its rows`);
                const mark = await until(() => document.querySelector('[data-testid="space-menu"] > :first-child'), 'The space’s mark is atop the list');
                const find = await until(search, `${view} has its search`);
                await wait(200);
                expect(left(mark), 'The space’s mark is on the screen’s edge').toBe(EDGE);
                expect(left(find), 'The search starts where the space’s mark does').toBe(EDGE);
                expect(left(face), 'The rows’ faces start where the space’s mark does').toBe(EDGE);
                const action = document.querySelector('.sticky > button');
                if (action) expect(left(action), 'The action card starts where the space’s mark does').toBe(EDGE);
                for (const control of host.querySelectorAll('[data-testid="work-page"] button')) {
                    const box = control.getBoundingClientRect();
                    if (!box.width || getComputedStyle(control).visibility === 'hidden') continue;
                    const name = control.getAttribute('aria-label') ?? control.textContent;
                    expect(Math.min(box.width, box.height), `${view}’s “${name}” is smaller than a finger`).toBeGreaterThanOrEqual(TAP);
                }
                expectNoSidewaysScroll(host, view);
                await shot(`__screenshots__/work-phone/${view.toLowerCase()}-${size[0]}-${theme}.png`);
            }, 30_000);
        }
    }

    it(`gives every Resources page’s title and line the page’s width at ${size[0]}px`, async () => {
        for (const kind of SPACE_KINDS) {
            const host = await openWork(`&show=resources&res=${kind}`, size, 'dark');
            const head = await until(() => document.querySelector<HTMLElement>('[data-testid="space-resources"] header'), `The ${kind} page has its head`);
            const title = head.querySelector('h1')!;
            const line = head.querySelector('p')!;
            const box = head.getBoundingClientRect();
            // The line takes the page's width, never a column beside the buttons.
            expect(line.getBoundingClientRect().width, `The ${kind} page’s line is squeezed`).toBeGreaterThan(box.width * 0.9);
            for (const button of head.querySelectorAll('button')) {
                const b = button.getBoundingClientRect();
                const t = title.getBoundingClientRect();
                expect(b.top >= t.bottom || b.bottom <= t.top || b.left >= t.right || b.right <= t.left, `The ${kind} page’s “${button.textContent}” lies over its title`).toBe(true);
                expect(b.right, `The ${kind} page’s “${button.textContent}” runs past the page`).toBeLessThanOrEqual(box.right + 0.5);
            }
            expectNoSidewaysScroll(host, `The ${kind} page`);
            if (kind === 'skills' || kind === 'connections') await shot(`__screenshots__/work-phone/resources-${kind}-${size[0]}.png`);
            unmount?.();
            unmount = null;
        }
    }, 90_000);
}

/** An iPhone's insets on the screen, as the app's viewport (viewport-fit=cover) lets them through. */
async function withHomeIndicator(run: () => Promise<void>) {
    const meta = document.createElement('meta');
    meta.name = 'viewport';
    meta.content = 'width=device-width, initial-scale=1, viewport-fit=cover';
    document.head.appendChild(meta);
    const insets = (top: number, bottom: number) => cdp().send('Emulation.setSafeAreaInsetsOverride', { insets: { top, topMax: top, bottom, bottomMax: bottom, left: 0, right: 0 } });
    await insets(47, HOME_INDICATOR);
    try {
        await run();
    } finally {
        await insets(0, 0);
        meta.remove();
    }
}

for (const [where, query] of [
    ['a channel', '&channel=ch_launch'],
    ['a DM', '&show=dms&channel=dm_priya'],
    ['a thread', '&channel=ch_launch&thread=l4'],
] as const) {
    it(`keeps ${where}’s composer clear of the home indicator`, async () => {
        await withHomeIndicator(async () => {
            await openWork(query, PHONES[0], 'dark');
            const attach = await until(() => document.querySelector('button[aria-label="Attach files"]'), `${where} has its composer`);
            await wait(200);
            expect(attach.getBoundingClientRect().bottom, `${where}’s composer reaches the home indicator`).toBeLessThanOrEqual(window.innerHeight - HOME_INDICATOR);
        });
    }, 30_000);
}

it('opens the Resources overview from the phone’s list', async () => {
    await openWork('&show=resources', PHONES[0], 'dark');
    const overview = await until(() => [...document.querySelectorAll('[data-testid="space-resources-nav"] button')].find((b) => b.textContent === 'Overview'), 'The list has its Overview');
    expect(overview.getAttribute('aria-current'), 'Nothing in the phone’s list is open').toBeNull();
    (overview as HTMLButtonElement).click();
    await until(() => [...document.querySelectorAll('[data-testid="space-resources"] h1')].find((h) => h.textContent === 'Resources'), 'Overview opens the overview');
}, 30_000);
