// @vitest-environment happy-dom
// The phone shell's swipe, with touches dispatched as a browser sends them to the element under the finger: across the
// page it opens the sidebar drawer and across the drawer closes it, settling by distance and speed; on a page one level
// down it slides the page off the screen it came from and goes back, and after that a swipe left comes forward again; an
// up-and-down drag, the canvas and a list scrolled sideways keep their own drags. The menu button and Escape still open
// and close it, moving focus in and back.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { BrowserRouter, useNavigate, useSearchParams } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PhoneBarBack } from '@/ui/phoneBar';
import { AppShell } from './AppShell';
import { isDeeper } from './phoneStack';
import { readDirection, releaseVelocity, settleMs, settlesOpen } from './phoneSwipe';

let clock = 1_000;

function touch(type: string, target: Element, x: number, y: number): Event {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'touches', { value: type === 'touchend' ? [] : [{ clientX: x, clientY: y }] });
    Object.defineProperty(event, 'timeStamp', { value: clock });
    target.dispatchEvent(event);
    return event;
}

const wait = (ms: number) => act(() => new Promise<void>((done) => setTimeout(done, ms)));

/** A finger down on `target` at `from` and moved to `to` over `ms`, still down. */
function drag(target: Element, from: [number, number], to: [number, number], ms = 120): Event[] {
    const steps = 6;
    clock += 1_000;
    touch('touchstart', target, ...from);
    const moves: Event[] = [];
    for (let i = 1; i <= steps; i++) {
        clock += ms / steps;
        moves.push(touch('touchmove', target, from[0] + ((to[0] - from[0]) * i) / steps, from[1] + ((to[1] - from[1]) * i) / steps));
    }
    return moves;
}

/** A finger from `from` to `to` over `ms`, then lifted, and what it moved given `settle` ms to come to rest (going back
 *  or forward also waits for the screen it lands on). */
async function swipe(target: Element, from: [number, number], to: [number, number], ms = 120, settle = 400): Promise<Event[]> {
    const moves = drag(target, from, to, ms);
    touch('touchend', target, ...to);
    await wait(settle);
    return moves;
}

function shell(page: ReactNode = <p>The chat</p>) {
    render(
        <AppShell
            isMobile
            sidebar={() => <nav aria-label="Pages">Chat · Work · Automations</nav>}
            collapsed={false}
            onCollapsedChange={() => {}}
            title="Chat"
            builder={null}
            builderShown={false}
            builderWidth={0}
            animate
        >
            {page}
        </AppShell>
    );
}

const drawer = () => document.getElementById('phone-menu')!;
const isOpen = () => drawer().dataset.open === 'true';

afterEach(cleanup);

describe('swiping on a phone', () => {
    it('opens the drawer on a quick swipe across the page and closes it on one back across it', async () => {
        shell();
        await swipe(screen.getByText('The chat'), [60, 300], [200, 304]);
        expect(isOpen()).toBe(true);
        expect(screen.getByRole('navigation', { name: 'Pages' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Open menu' }).getAttribute('aria-expanded')).toBe('true');

        await swipe(screen.getByRole('navigation', { name: 'Pages' }), [250, 300], [120, 296]);
        expect(isOpen()).toBe(false);
    });

    it('settles by how far it got when the finger slows to a stop', async () => {
        shell();
        await swipe(screen.getByText('The chat'), [60, 300], [120, 300], 1_800);
        expect(isOpen(), 'a fifth of the way, let go slowly: back shut').toBe(false);

        await swipe(screen.getByText('The chat'), [20, 300], [230, 300], 1_800);
        expect(isOpen(), 'past halfway, let go slowly: open').toBe(true);
    });

    it('leaves an up-and-down drag to the page', async () => {
        shell();
        const moves = await swipe(screen.getByText('The chat'), [60, 400], [80, 150]);
        expect(isOpen()).toBe(false);
        expect(moves.some((move) => move.defaultPrevented)).toBe(false);
    });

    it('goes back on a page one level down, and only once it has gone far enough', async () => {
        const onBack = vi.fn();
        shell(<PhoneBarBack label="Channels" onBack={onBack} />);
        const page = document.querySelector('main')!;

        await swipe(page, [40, 300], [72, 300], 1_200, 1_200);
        expect(onBack, 'a short slow pull slides back').not.toHaveBeenCalled();

        await swipe(page, [40, 300], [180, 300], 120, 1_200);
        expect(onBack).toHaveBeenCalledTimes(1);
        expect(isOpen(), 'the swipe went back, not into the menu').toBe(false);
    });

    it('slides the page off the screen it came from, then brings it back in with a swipe the other way', async () => {
        function Inbox() {
            const [params] = useSearchParams();
            const navigate = useNavigate();
            return params.get('open') ? (
                <>
                    <PhoneBarBack label="Inbox" onBack={() => navigate('/?tab=inbox')} />
                    <p>The message</p>
                </>
            ) : (
                <button type="button" onClick={() => navigate('/?tab=inbox&open=1')}>
                    Open the message
                </button>
            );
        }
        window.history.replaceState(null, '', '/?tab=inbox');
        render(
            <BrowserRouter>
                <AppShell isMobile sidebar={() => null} collapsed={false} onCollapsedChange={() => {}} title="Inbox" builder={null} builderShown={false} builderWidth={0} animate>
                    <Inbox />
                </AppShell>
            </BrowserRouter>
        );
        await act(async () => fireEvent.click(screen.getByText('Open the message')));
        await wait(100);
        expect(screen.getByText('The message')).toBeTruthy();

        // Mid-swipe, the list it came from is under the page (a picture of it) and the page has moved off it.
        const page = document.querySelector('main')!;
        drag(page, [40, 300], [240, 300]);
        await wait(50);
        expect(screen.getByText('Open the message').closest('[inert]'), 'the list, as a picture under the page').toBeTruthy();
        expect(page.closest<HTMLElement>('[data-menu], .fixed')!.style.transform).toMatch(/translateX\([1-9]/);
        touch('touchend', page, 240, 300);
        await wait(1_200);
        expect(window.location.search).toBe('?tab=inbox');
        expect(screen.getAllByText('Open the message'), 'the real list, the picture gone').toHaveLength(1);
        expect(screen.queryByText('The message')).toBeNull();

        await swipe(document.querySelector('main')!, [300, 300], [120, 300], 120, 1_200);
        expect(window.location.search).toBe('?tab=inbox&open=1');
        expect(screen.getByText('The message')).toBeTruthy();
    });

    it('leaves sideways drags to the canvas and to a list scrolled sideways', async () => {
        shell(
            <>
                <div className="react-flow">
                    <span>A step on the canvas</span>
                </div>
                <div style={{ overflowX: 'auto' }} data-testid="row">
                    <span>A wide table</span>
                </div>
            </>
        );
        await swipe(screen.getByText('A step on the canvas'), [60, 300], [220, 300]);
        expect(isOpen()).toBe(false);

        const row = screen.getByTestId('row');
        Object.defineProperty(row, 'scrollWidth', { value: 900 });
        Object.defineProperty(row, 'clientWidth', { value: 320 });
        row.scrollLeft = 120;
        await swipe(screen.getByText('A wide table'), [60, 300], [220, 300]);
        expect(isOpen(), 'it scrolls back to its start first').toBe(false);
    });

    it('opens from the menu button with focus inside, and Escape puts focus back on the button', async () => {
        shell();
        const button = screen.getByRole('button', { name: 'Open menu' });
        await act(async () => fireEvent.click(button));
        expect(isOpen()).toBe(true);
        expect(document.activeElement).toBe(drawer());

        await act(async () => fireEvent.keyDown(document, { key: 'Escape' }));
        expect(isOpen()).toBe(false);
        expect(document.activeElement).toBe(button);
    });
});

describe('reading a swipe', () => {
    it('reads a touch as a swipe only once it leans sideways', () => {
        expect(readDirection(4, 2)).toBeNull();
        expect(readDirection(20, 6)).toBe('right');
        expect(readDirection(-20, 6)).toBe('left');
        expect(readDirection(12, 14)).toBe('scroll');
    });

    it('keeps a picture for a place only when back from it lands where the tap was', () => {
        expect(isDeeper('/dashboard?tab=work&view=dms', '/dashboard?tab=work&view=dms&channel=c1')).toBe(true);
        expect(isDeeper('/settings', '/settings/notifications')).toBe(true);
        expect(isDeeper('/dashboard?tab=work&view=dms', '/dashboard?tab=work&view=agents'), 'another view, not inside this one').toBe(false);
        expect(isDeeper('/dashboard?tab=work&channel=c1', '/dashboard?tab=work&channel=c2'), 'a sibling').toBe(false);
        expect(isDeeper('/dashboard?tab=work', '/dashboard?tab=work')).toBe(false);
    });

    it('settles where a flick was heading, else on the nearer side', () => {
        expect(settlesOpen(0.2, 0.8)).toBe(true);
        expect(settlesOpen(0.9, -0.8)).toBe(false);
        expect(settlesOpen(0.6, 0)).toBe(true);
        expect(settlesOpen(0.4, 0.1)).toBe(false);
    });

    it('takes its speed from the last moments before letting go, and its settle time from that speed', () => {
        const samples = [
            { t: 0, x: 0 },
            { t: 50, x: 40 },
            { t: 100, x: 100 },
        ];
        expect(releaseVelocity(samples, 100)).toBeCloseTo(1);
        expect(releaseVelocity(samples, 300), 'stopped before letting go').toBe(0);
        expect(settleMs(150, 3)).toBeLessThan(settleMs(150, 1));
        expect(settleMs(150, 0)).toBe(320);
        expect(settleMs(10, 5)).toBe(170);
    });
});
