// The space's name atop Work's list opens the space's menu, from a click and from the keyboard, in every view (Home,
// Agents, DMs, Resources): on a laptop with the list beside what's open, and folded then opened over it, and on a phone.
// In a real browser, since what stopped it was layout: the folded rail's Show slot lay over the name in Agents and DMs.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { useState, type ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { page, userEvent } from 'vitest/browser';
import { afterEach, expect, it } from 'vitest';
import { PhoneBarSlotProvider } from '~/components/shell/AppShell';
import { WorkClientContext } from '~/cloud/components/work/client';
import { fakeWork } from '~/cloud/components/work/fixtures/workApi';
import { REST_MS } from '~/cloud/components/work/listRail';
import { WorkLiveContext } from '~/cloud/components/work/live';
import { AutomationsContext, Work } from '~/cloud/components/work/Work';

const USER = { email: 'dhruv@example.com', display_name: 'Dhruv Yadav' };
const NO_AUTOMATIONS = { list: async () => [], add: async () => undefined };
const VIEWS = [
    ['Home', ''],
    ['Agents', 'agents'],
    ['DMs', 'dms'],
    ['Resources', 'resources'],
] as const;
const MEMBERS = 'Members and agents';

let unmount: (() => void) | null = null;
afterEach(() => {
    unmount?.();
    unmount = null;
    localStorage.clear();
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

/** Work in the NoClick space, on `show` (Home when empty), at a laptop's or a phone's width. */
async function openWork(show: string, device: 'laptop' | 'phone', width = 1600) {
    const phone = device === 'phone';
    await page.viewport(phone ? 390 : width, phone ? 844 : 900);
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
    const url = `/dashboard?tab=work&space=ws_noclick${show ? `&show=${show}` : ''}`;
    const router = createMemoryRouter([{ path: '/dashboard', element: phone ? <PhoneBar>{work}</PhoneBar> : work }], { initialEntries: [url] });
    flushSync(() => root.render(<RouterProvider router={router} />));
    unmount = () => {
        flushSync(() => root.unmount());
        host.remove();
    };
    return host;
}

const trigger = () => document.querySelector<HTMLElement>('[data-testid="space-menu"]');
const list = () => document.querySelector<HTMLElement>('nav[aria-label="The list"]');
const menu = () => document.querySelector<HTMLElement>('[role="menu"]');
const item = (name: string) => [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) => el.textContent?.trim() === name) ?? null;
const shows = (el: HTMLElement) => getComputedStyle(el.closest('[data-space-head]') ?? el).visibility === 'visible';

/** What a pointer at `el`'s center lands on is `el`, or in it. */
function expectReaches(el: HTMLElement, what: string) {
    const box = el.getBoundingClientRect();
    const at = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    expect(el.contains(at), `${what} takes the pointer at its center, not ${at?.outerHTML.slice(0, 120)}`).toBe(true);
}

/** The space's name, shown and reachable, opens its menu on a click; the whole menu takes the pointer; Esc closes it. */
async function opensOnClick() {
    const name = await until(() => trigger()?.querySelector<HTMLElement>('span.truncate'), 'The space’s name is atop the list');
    await until(() => shows(name) && name, 'The space’s name shows');
    // Where the list glides open, once it's settled: mid-glide a slot's hit area may not yet lie where it rests.
    await wait(300);
    expectReaches(name, 'The space’s name');
    await userEvent.click(name);
    const members = await until(() => item(MEMBERS), 'A click on the name opens the space’s menu');
    // Nothing clips it: each of its rows takes the pointer.
    for (const row of document.querySelectorAll<HTMLElement>('[role="menuitem"]')) expectReaches(row, `The menu’s “${row.textContent}”`);
    const box = menu()!.getBoundingClientRect();
    expect(box.right).toBeLessThanOrEqual(window.innerWidth);
    expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
    expectReaches(members, MEMBERS);
    await userEvent.keyboard('{Escape}');
    await until(() => !menu(), 'Esc closes the menu');
}

/** From the keyboard: Enter on the focused name opens the menu on its first row; Esc closes it, back on the name. */
async function opensFromKeyboard() {
    trigger()!.focus();
    expect(document.activeElement).toBe(trigger());
    await userEvent.keyboard('{Enter}');
    await until(() => item(MEMBERS), 'Enter on the name opens the space’s menu');
    await until(() => menu()!.contains(document.activeElement), 'The menu takes the focus');
    await userEvent.keyboard('{Escape}');
    await until(() => !menu(), 'Esc closes the menu');
    await until(() => document.activeElement === trigger(), 'The focus is back on the name');
}

for (const [view, show] of VIEWS) {
    it(`opens the space’s menu from its name in ${view}, the list beside what’s open, on a laptop`, async () => {
        await openWork(show, 'laptop');
        await opensOnClick();
        await opensFromKeyboard();
        if (list()?.querySelector('.work-rail-show')) expect(list()!.dataset.docked).toBe('true');
    }, 30_000);

    it(`opens the space’s menu from its name in ${view} on a phone`, async () => {
        await openWork(show, 'phone');
        await opensOnClick();
        await opensFromKeyboard();
    }, 30_000);
}

for (const [view, show, noun] of [
    ['Agents', 'agents', 'agents'],
    ['DMs', 'dms', 'people'],
] as const) {
    it(`opens the space’s menu from its name in ${view} with the list folded, then opened over the conversation`, async () => {
        // A laptop too narrow for the list beside what's open: it folds to the rail, the name hidden.
        await openWork(show, 'laptop', 1280);
        // The pointer away from the list, where the last test may have left it resting.
        await userEvent.hover(await until(() => document.querySelector<HTMLElement>('nav[aria-label="Spaces"]'), 'The spaces’ rail'));
        const showList = await until(() => list()?.querySelector<HTMLElement>(`button[aria-label="Show ${noun}"]`), 'The list folds to its rail');
        await until(() => list()!.dataset.docked === 'false' && !shows(trigger()!), 'Folded, the name is hidden');

        // Opened by its Show button, the name opens the menu; the list stays open under it and after Esc.
        await userEvent.click(showList);
        await until(() => list()!.dataset.expanded === 'true', 'Show opens the list over the conversation');
        await opensOnClick();
        expect(list()!.dataset.expanded).toBe('true');
        await opensFromKeyboard();
        expect(list()!.dataset.expanded).toBe('true');

        // Opened by resting on it: the menu holds the list open while the pointer crosses it to a row.
        await userEvent.keyboard('{Escape}');
        await until(() => list()!.dataset.expanded === 'false', 'Esc folds it again');
        // Folded by Esc under the pointer, resting opens it again only once the pointer has left.
        await userEvent.hover(document.querySelector<HTMLElement>('nav[aria-label="Spaces"]')!);
        const face = list()!.querySelector<HTMLElement>('li > button')!;
        await userEvent.hover(face);
        await wait(REST_MS + 150);
        await until(() => list()!.dataset.expanded === 'true', 'Resting on the rail opens the list');
        await userEvent.click(trigger()!.querySelector<HTMLElement>('span.truncate')!);
        const members = await until(() => item(MEMBERS), 'The name opens the menu');
        await userEvent.hover(face, { force: true });
        await wait(600);
        expect(list()!.dataset.expanded, 'The list stays open while its menu is').toBe('true');
        await userEvent.click(members);
        await until(() => !menu(), 'Picking a row closes the menu');

        // From the keyboard alone: Show, then back from its search to the name.
        await userEvent.keyboard('{Escape}');
        await until(() => list()!.dataset.expanded === 'false', 'Esc folds it again');
        showList.focus();
        await userEvent.keyboard('{Enter}');
        await until(() => document.activeElement?.matches('nav[aria-label="The list"] label > input'), 'Show from the keyboard goes on to the search');
        // Back past the list's action and the fold glyph, the name is the header's first stop.
        for (let i = 0; i < 4 && document.activeElement !== trigger(); i++) await userEvent.tab({ shift: true });
        expect(document.activeElement).toBe(trigger());
        await opensFromKeyboard();
        expect(list()!.dataset.expanded).toBe('true');
    }, 45_000);
}
