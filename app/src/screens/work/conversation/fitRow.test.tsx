// @vitest-environment happy-dom
// The row that folds its pills to fit, at the width where it once looped: its strip one pixel too wide when each width
// is rounded alone, and fitting again once the first pill folds. It folds that pill and settles, rather than folding
// and unfolding it until the page fails ("Maximum update depth exceeded"). happy-dom lays nothing out, so each width
// is set here as a browser measures it: fractional, and rounded where `offsetWidth`/`clientWidth` round it.
import { cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { useFitRow } from './fitRow';

/** The row the footer gave its pills at 360px (296px), and its pills: the first to fold, then the rest. */
const ROOM = 296;
const FOLDS_FIRST = { full: 130.4, folded: 30.6 };
const THE_REST = 150.2;
const GAPS = 16;

function widthOf(el: Element): number {
    const html = el as HTMLElement;
    if (html.dataset.row !== undefined) return ROOM;
    if (html.dataset.fold === '0') return html.dataset.folded ? FOLDS_FIRST.folded : FOLDS_FIRST.full;
    if (html.dataset.fold === '1') return THE_REST;
    if (html.dataset.strip !== undefined) return [...html.children].reduce((sum, child) => sum + widthOf(child), 0) + GAPS;
    return 0;
}

const props = ['offsetWidth', 'clientWidth'] as const;
const saved = new Map<string, PropertyDescriptor | undefined>();
let renders = 0;

beforeEach(() => {
    renders = 0;
    for (const p of props) {
        saved.set(p, Object.getOwnPropertyDescriptor(HTMLElement.prototype, p));
        Object.defineProperty(HTMLElement.prototype, p, { configurable: true, get(this: HTMLElement) { return Math.round(widthOf(this)); } });
    }
    saved.set('rect', Object.getOwnPropertyDescriptor(Element.prototype, 'getBoundingClientRect'));
    Object.defineProperty(Element.prototype, 'getBoundingClientRect', { configurable: true, value(this: Element) { return { width: widthOf(this), height: 28, top: 0, left: 0, right: widthOf(this), bottom: 28, x: 0, y: 0 }; } });
});

afterEach(() => {
    cleanup();
    for (const p of props) Object.defineProperty(HTMLElement.prototype, p, saved.get(p)!);
    Object.defineProperty(Element.prototype, 'getBoundingClientRect', saved.get('rect')!);
});

function Row() {
    const fit = useFitRow(true);
    renders += 1;
    return (
        <div ref={fit.row} data-row="">
            <div ref={fit.inner} data-strip="">
                {[0, 1].map((rank) => (
                    <span key={rank} data-fold={rank} data-folded={fit.folded(rank) || undefined} />
                ))}
            </div>
        </div>
    );
}

it('folds the pill that doesn’t fit and settles, at the width where rounding made it loop', () => {
    const { container } = render(<Row />);
    expect(container.querySelector('[data-fold="0"]')?.hasAttribute('data-folded')).toBe(true);
    expect(container.querySelector('[data-fold="1"]')?.hasAttribute('data-folded')).toBe(false);
    expect(renders).toBeLessThan(5);
});
