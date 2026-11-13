// Home's list folded to the rail, in the real browser over Work's fixture at a laptop's width (run at 1280): each
// channel's and Threads' glyph sits on the rail's one line (the Show button's, the search circle's), its tile around
// it; Threads open draws its tile and the current mark as a channel does; a channel with an @ count and an unread
// count shows one count, the @ one, inside the rail. Nothing real is called.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { fakeWork } from '~/cloud/components/work/fixtures/workApi';
import { WorkClientContext } from '~/cloud/components/work/client';
import { WorkLiveContext } from '~/cloud/components/work/live';
import { AutomationsContext, Work } from '~/cloud/components/work/Work';
import { nc } from '~/lib/nc';

const USER = { email: 'dhruv@example.com', display_name: 'Dhruv Yadav' };
const NO_AUTOMATIONS = { list: async () => [], add: async () => undefined };
const FOLDED_KEY = 'nc-work-list-folded';

const centre = (el: Element) => {
    const r = el.getBoundingClientRect();
    return r.left + r.width / 2;
};
/** Where a row's folded tile (its ::after) is centred, on the page. */
const tileCentre = (row: HTMLElement) => {
    const tile = getComputedStyle(row, '::after');
    return row.getBoundingClientRect().left + parseFloat(tile.left) + parseFloat(tile.width) / 2;
};

export default async function () {
    if (window.innerWidth < 1024) return;
    const fake = fakeWork({ mentions: true });
    const incidents = fake.channels.find((c) => c.name === 'incidents')!;
    Object.assign(incidents, { mention_count: 2 });
    let folded: string | null = null;
    try {
        folded = window.localStorage.getItem(FOLDED_KEY);
        window.localStorage.setItem(FOLDED_KEY, '1');
    } catch {
        // No storage: the rail folds only for want of room.
    }
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;inset:0;display:flex;flex-direction:column;z-index:2147483000;background:hsl(var(--background))';
    document.body.appendChild(host);
    const root = createRoot(host);
    const router = createMemoryRouter(
        [
            {
                path: '/dashboard',
                element: (
                    <WorkClientContext.Provider value={fake.client}>
                        <WorkLiveContext.Provider value={fake.live}>
                            <AutomationsContext.Provider value={NO_AUTOMATIONS}>
                                <Work user={USER} />
                            </AutomationsContext.Provider>
                        </WorkLiveContext.Provider>
                    </WorkClientContext.Provider>
                ),
            },
        ],
        { initialEntries: ['/dashboard?tab=work'] }
    );
    flushSync(() => root.render(<RouterProvider router={router} />));
    try {
        const rail = () => host.querySelector<HTMLElement>('nav[aria-label="The list"][data-expanded="false"]');
        // Threads, then each channel's row.
        const rows = () => [...(rail()?.querySelectorAll<HTMLElement>('[data-rail-go], [data-testid$="-channels"] li > button:first-child') ?? [])];
        await nc.wait.until(() => rows().length >= 4, 10000);
        // The column's width and the glyphs' move both ease in 220ms.
        await nc.wait.ms(400);
        const line = centre(rail()!.querySelector('.work-rail-show')!);
        nc.assert.ok(Math.abs(centre(rail()!.querySelector('[data-rail-search] > svg')!) - line) < 0.6, 'The search sits on the rail’s line');
        for (const row of rows()) {
            const name = row.querySelector('[data-rail-text]')?.textContent;
            nc.assert.ok(Math.abs(centre(row.querySelector('svg')!) - line) < 0.6, `${name}’s glyph sits on the rail’s line (${centre(row.querySelector('svg')!)} vs ${line})`);
            nc.assert.ok(Math.abs(tileCentre(row) - line) < 0.6, `${name}’s tile is centred on it (${tileCentre(row)} vs ${line})`);
        }

        // A channel with an @ count and an unread count shows the @ one alone, inside the rail.
        const row = rows().find((r) => r.querySelector('[data-rail-text]')?.textContent === 'incidents')!;
        await nc.wait.until(() => row.querySelectorAll('[data-count]').length === 2, 5000);
        const shown = [...row.querySelectorAll<HTMLElement>('[data-count]')].filter((c) => getComputedStyle(c).display !== 'none');
        nc.assert.equal(shown.length, 1, 'One count on a folded row');
        nc.assert.ok(/mention/.test(shown[0].getAttribute('aria-label') ?? ''), 'and it’s the @ count');
        nc.assert.ok(shown[0].getBoundingClientRect().right <= rail()!.getBoundingClientRect().right - 1, 'The count stays inside the rail');

        // Threads open: its tile and the current mark, as a channel's.
        await router.navigate('/dashboard?tab=work&channel=threads');
        await nc.wait.until(() => rail()?.querySelector('[data-rail-go]')?.getAttribute('aria-current') === 'page', 5000);
        const threads = rail()!.querySelector<HTMLElement>('[data-rail-go]')!;
        nc.assert.ok(getComputedStyle(threads, '::after').backgroundColor !== 'rgba(0, 0, 0, 0)', 'Threads open has its tile');
        nc.assert.ok(getComputedStyle(threads, '::before').content !== 'none', 'and the current mark');
    } finally {
        root.unmount();
        host.remove();
        try {
            if (folded === null) window.localStorage.removeItem(FOLDED_KEY);
            else window.localStorage.setItem(FOLDED_KEY, folded);
        } catch {
            // Nothing was kept.
        }
    }
}
