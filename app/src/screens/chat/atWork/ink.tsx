// Text that sits right. Two pieces the tab of what's at work is built on:
//
// - Ink centring. A line box centres the font's ascent and descent, not the letters drawn, so a label with a
//   descender ("Raise cap") reads high-bottomed and one without ("Review") low: measured, 8px over 7 and 8 over 10 in
//   the same 28px pill. `useInkCentring` measures each control's own text with the browser's font metrics (canvas
//   measureText for the ink, a zero-size probe for the baseline) and moves the text by whole device pixels so the
//   space above the first ink row equals the space below the last.
// - Fitting by words. `FitWords` never ellipses: it drops its quieter part first, then whole words from the end (and
//   any connective left dangling) until the line fits.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/ui/utils';

let canvas: CanvasRenderingContext2D | null = null;
function context(): CanvasRenderingContext2D {
    canvas ??= document.createElement('canvas').getContext('2d')!;
    return canvas;
}

function fontOf(el: Element): string {
    const s = getComputedStyle(el);
    return `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
}

const drawn = new Map<string, Profile>();

/** How strongly each device-pixel row of a line's text shows against its ground, and which row its baseline is. */
interface Profile {
    rows: number[];
    base: number;
}

/** The opaque colour the text is drawn on: the nearest background that isn't see-through. */
function groundOf(el: Element): string {
    for (let at: Element | null = el; at; at = at.parentElement) {
        const bg = getComputedStyle(at).backgroundColor;
        const alpha = bg.match(/rgba?\([^)]*,\s*([\d.]+)\)/)?.[1];
        if (bg !== 'transparent' && (alpha === undefined || parseFloat(alpha) > 0.9)) return bg;
    }
    return getComputedStyle(document.body).backgroundColor;
}

function luminance(r: number, g: number, b: number): number {
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** A line's text drawn at this screen's pixel density, in its own faces and colours on its ground, read row by row as
 *  the padding check reads the screen. */
function profile(el: HTMLElement): Profile {
    // Each run of text in its own face and colour, on the colour it sits on: a medium-weight name inks its top row
    // darker than regular words, and light text on a dark ground reads heavier than dark on light.
    const runs: { text: string; font: string; color: string }[] = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) if (node.textContent) runs.push({ text: node.textContent, font: fontOf(node.parentElement!), color: getComputedStyle(node.parentElement!).color });
    const ground = groundOf(el);
    const dpr = window.devicePixelRatio || 1;
    const key = `${dpr}|${ground}|${runs.map((r) => `${r.font}|${r.color}|${r.text}`).join('||')}`;
    const known = drawn.get(key);
    if (known) return known;
    const size = parseFloat(getComputedStyle(el).fontSize);
    // A line React has just swapped out has no style to read: nothing to centre.
    if (!el.isConnected || !(size > 0) || !runs.length) return { rows: [], base: 0 };
    const ctx = context();
    const width = Math.ceil(
        runs.reduce((w, r) => {
            ctx.font = r.font;
            return w + ctx.measureText(r.text).width;
        }, 8)
    );
    const height = Math.ceil(size * 2.4);
    const board = document.createElement('canvas');
    board.width = width * dpr;
    board.height = height * dpr;
    const draw = board.getContext('2d', { willReadFrequently: true })!;
    draw.scale(dpr, dpr);
    draw.fillStyle = ground;
    draw.fillRect(0, 0, width, height);
    const base = Math.round(size * 1.6);
    let x = 4;
    for (const run of runs) {
        draw.font = run.font;
        draw.fillStyle = run.color;
        draw.fillText(run.text, x, base);
        x += draw.measureText(run.text).width;
    }
    const { data } = draw.getImageData(0, 0, board.width, board.height);
    const g = luminance(data[0], data[1], data[2]);
    const rows: number[] = [];
    for (let y = 0; y < board.height; y++) {
        let peak = 0;
        for (let i = 0; i < board.width; i++) {
            const o = (y * board.width + i) * 4;
            peak = Math.max(peak, Math.abs(luminance(data[o], data[o + 1], data[o + 2]) - g));
        }
        rows.push(peak);
    }
    const found = { rows, base: base * dpr };
    // Kept only once the page's fonts are in: before, the canvas may have drawn a stand-in face.
    if (document.fonts.status === 'loaded') drawn.set(key, found);
    return found;
}

function baseline(el: HTMLElement, at: 'start' | 'end'): number {
    const probe = document.createElement('span');
    probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
    if (at === 'start') el.prepend(probe);
    else el.append(probe);
    const y = probe.getBoundingClientRect().top;
    probe.remove();
    return y;
}

/** The text elements that belong to `control`, not to a control inside it. */
function linesOf(control: HTMLElement): HTMLElement[] {
    const marked = [...control.querySelectorAll<HTMLElement>('[data-ink-line]')].filter((el) => el.closest('[data-ink]') === control && el.textContent?.trim());
    return marked;
}

function centre(controls: HTMLElement[]) {
    const dpr = window.devicePixelRatio || 1;
    const bodies = controls.map((c) => [...c.querySelectorAll<HTMLElement>('[data-ink-body]')].find((b) => b.closest('[data-ink]') === c) ?? null);
    bodies.forEach((b) => b && (b.style.transform = ''));
    const moves = controls.map((control, i) => {
        const body = bodies[i];
        const lines = linesOf(control);
        if (!body || !lines.length) return null;
        // In device pixels, as they're painted: a box's edge and a baseline land on whole ones, a baseline halfway
        // between two on the upper (text at 2× sat a device pixel higher than rounding put it).
        const px = (v: number) => Math.round(v * dpr);
        const line = (v: number) => Math.ceil(v * dpr - 0.5);
        const box = control.getBoundingClientRect();
        const first = lines[0];
        const last = lines[lines.length - 1];
        // Ink is what shows at least half as strongly as the strongest of its lines (a quiet second line's faint tail
        // doesn't count), as the check reads it.
        const head = profile(first);
        const tail = profile(last);
        if (!head.rows.length || !tail.rows.length) return null;
        const peak = Math.max(...head.rows, ...tail.rows);
        const firstRow = head.rows.findIndex((a) => a >= 0.5 * peak);
        const lastRow = tail.rows.length - 1 - [...tail.rows].reverse().findIndex((a) => a >= 0.5 * peak);
        if (firstRow < 0 || lastRow >= tail.rows.length) return null;
        const top = line(baseline(first, 'start')) - (head.base - firstRow);
        const bottom = line(baseline(last, 'end')) + (lastRow + 1 - tail.base);
        // Half the difference; an odd pixel goes under the text, never over it.
        return Math.floor((px(box.bottom) - bottom - (top - px(box.top))) / 2) / dpr;
    });
    bodies.forEach((b, i) => b && moves[i] && (b.style.transform = `translateY(${moves[i]}px)`));
}

/** Keeps every `[data-ink]` control under `root` ink-centred (its `[data-ink-body]` moved, its `[data-ink-line]`
 *  measured) as its text, size or fonts change. */
export function useInkCentring(root: React.RefObject<HTMLElement | null>) {
    useLayoutEffect(() => {
        const el = root.current;
        if (!el) return;
        let frame = 0;
        // eslint-disable-next-line prefer-const
        let seen: MutationObserver;
        const run = () => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
                centre([...el.querySelectorAll<HTMLElement>('[data-ink]')]);
                // Its own baseline probes come and go: not a change to answer.
                seen.takeRecords();
            });
        };
        seen = new MutationObserver(run);
        run();
        void document.fonts.ready.then(() => {
            drawn.clear();
            run();
        });
        seen.observe(el, { subtree: true, childList: true, characterData: true });
        const sized = new ResizeObserver(run);
        sized.observe(el);
        // A control that slid or grew into place (a tab opening, a sheet rising) lands on other pixel rows than it was
        // measured on mid-way: measured again once it stops.
        el.addEventListener('transitionend', run);
        el.addEventListener('animationend', run);
        return () => {
            cancelAnimationFrame(frame);
            seen.disconnect();
            sized.disconnect();
            el.removeEventListener('transitionend', run);
            el.removeEventListener('animationend', run);
        };
    }, [root]);
}

const DANGLING = /^(and|or|the|a|an|to|of|on|in|into|for|with|from|at|by|its|their|your|is|are|was|then|but|so|as|that|this|instead|every|it|until|before|after|while)$/i;

function cut(words: string[]): string[] {
    const out = words.slice(0, -1);
    // A connective or a bare number left at the end is a fragment, not the start of a thought.
    while (out.length && (DANGLING.test(out[out.length - 1].replace(/[,;:]$/, '')) || /^\d+[,;:]?$/.test(out[out.length - 1]))) out.pop();
    if (out.length) out[out.length - 1] = out[out.length - 1].replace(/[,;:·–-]+$/, '');
    return out;
}

/** One line that fits its width without an ellipsis: `lead` is kept whole, `quiet` (after " · ") goes first, then
 *  whole words from the end of `text` (and any connective left dangling), then `text` altogether. Marked
 *  `data-ink-line` for ink centring. */
export function FitWords({ lead, text = '', quiet, className, leadClassName, textClassName, quietClassName }: { lead?: string; text?: string; quiet?: string; className?: string; leadClassName?: string; textClassName?: string; quietClassName?: string }) {
    const ref = useRef<HTMLSpanElement>(null);
    const [shown, setShown] = useState<{ lead?: string; text: string; quiet?: string }>({ lead, text, quiet });
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el) return;
        const fit = () => {
            const width = el.clientWidth;
            const ctx = context();
            const measure = (part: string, cls: string) => {
                const node = el.querySelector<HTMLElement>(`[data-part=${cls}]`) ?? el;
                ctx.font = fontOf(node);
                return ctx.measureText(part).width;
            };
            const joint = lead && text ? ' · ' : '';
            const leadW = lead ? measure(lead, 'lead') : 0;
            const fits = (t: string, q?: string) => leadW + (t ? measure(joint + t, 'text') : 0) + (q ? measure(` · ${q}`, 'quiet') : 0) <= width + 0.5;
            if (fits(text, quiet)) return setShown({ lead, text, quiet });
            let words = text.split(/\s+/).filter(Boolean);
            while (words.length && !fits(words.join(' '))) words = cut(words);
            if (words.length || !lead || leadW <= width + 0.5) return setShown({ lead, text: words.join(' ') });
            // Even the part kept whole doesn't fit: it loses words too, never letters.
            let kept = lead.split(/\s+/);
            while (kept.length > 1 && measure(kept.join(' '), 'lead') > width + 0.5) kept = cut(kept);
            setShown({ lead: kept.join(' '), text: '' });
        };
        fit();
        const sized = new ResizeObserver(fit);
        sized.observe(el);
        void document.fonts.ready.then(fit);
        return () => sized.disconnect();
    }, [lead, text, quiet]);
    return (
        <span ref={ref} data-ink-line className={cn('block overflow-hidden whitespace-nowrap', className)}>
            {shown.lead && (
                <span data-part="lead" className={leadClassName}>
                    {shown.lead}
                </span>
            )}
            {shown.text && (
                <span data-part="text" className={textClassName}>
                    {lead ? ' · ' : ''}
                    {shown.text}
                </span>
            )}
            {shown.quiet && (
                <span data-part="quiet" className={quietClassName}>
                    {' · '}
                    {shown.quiet}
                </span>
            )}
        </span>
    );
}

/** A label inside a control, marked for ink centring. */
export function Ink({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <span data-ink-body data-ink-line className={cn('inline-block', className)}>
            {children}
        </span>
    );
}
