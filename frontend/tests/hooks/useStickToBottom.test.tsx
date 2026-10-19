// @vitest-environment jsdom
// A chat opens on its newest message and stays there while what renders after a message (markdown from its chunk, a
// diagram, a card) grows the thread, even when the scroll event of the hook's own pin arrives after that growth, or
// when the thread's own box shrinks under it (a card docking on the composer); a reader who scrolled up to read
// history stays where they are.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStickToBottom } from '~/hooks/useStickToBottom';

// jsdom lays nothing out: the scroller's box is this one, its scrollTop clamped as a browser clamps it.
const box = { height: 0, client: 400, top: 0 };
const grown: ResizeObserverCallback[] = [];
const watched: { el: Element; callback: ResizeObserverCallback }[] = [];

function Thread({ items }: { items: string[] }) {
    const { ref, onScroll } = useStickToBottom<HTMLDivElement>([items.length]);
    return (
        <div ref={ref} onScroll={onScroll} data-testid="scroller">
            <div>
                {items.map((item) => (
                    <p key={item}>{item}</p>
                ))}
            </div>
        </div>
    );
}

const scroller = () => screen.getByTestId('scroller');
const grow = (height: number) => {
    box.height = height;
    for (const callback of grown) callback([], {} as ResizeObserver);
};
const resized = (el: Element) => {
    for (const w of watched) if (w.el === el) w.callback([], {} as ResizeObserver);
};
const fromBottom = () => box.height - box.top - box.client;

beforeEach(() => {
    Object.assign(box, { height: 1000, client: 400, top: 0 });
    grown.length = 0;
    watched.length = 0;
    vi.stubGlobal(
        'ResizeObserver',
        class {
            callback: ResizeObserverCallback;
            constructor(callback: ResizeObserverCallback) {
                this.callback = callback;
                grown.push(callback);
            }
            observe(el: Element) {
                watched.push({ el, callback: this.callback });
            }
            unobserve() {}
            disconnect() {}
        }
    );
    const sized = (el: HTMLElement) => el.dataset.testid === 'scroller';
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get() { return sized(this) ? box.height : 0; } });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return sized(this) ? box.client : 0; } });
    Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
        configurable: true,
        get() {
            return sized(this) ? box.top : 0;
        },
        set(value: number) {
            if (sized(this)) box.top = Math.max(0, Math.min(value, box.height - box.client));
        },
    });
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    for (const key of ['scrollHeight', 'clientHeight', 'scrollTop']) delete (HTMLElement.prototype as unknown as Record<string, unknown>)[key];
});

describe('useStickToBottom', () => {
    it('opens on the newest message and follows the thread as it grows after it drew', () => {
        render(<Thread items={['a', 'b', 'c']} />);
        expect(fromBottom()).toBe(0);
        // The pin's own scroll event arrives after more of the thread has drawn: it isn't the reader leaving.
        box.height = 1300;
        fireEvent.scroll(scroller());
        grow(1300);
        expect(fromBottom()).toBe(0);
        grow(1650);
        expect(fromBottom()).toBe(0);
    });

    it('keeps the newest message in view when its box shrinks under it', () => {
        render(<Thread items={['a', 'b', 'c']} />);
        expect(fromBottom()).toBe(0);
        box.client = 250;
        resized(scroller());
        expect(fromBottom()).toBe(0);
    });

    it('leaves a reader who scrolled up where they are, and follows again once they are back at the bottom', () => {
        const { rerender } = render(<Thread items={['a', 'b', 'c']} />);
        box.top = 200;
        fireEvent.scroll(scroller());
        grow(1400);
        rerender(<Thread items={['a', 'b', 'c', 'd']} />);
        expect(box.top).toBe(200);

        box.top = box.height - box.client;
        fireEvent.scroll(scroller());
        grow(1800);
        expect(fromBottom()).toBe(0);
    });
});
