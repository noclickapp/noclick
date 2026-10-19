// The hero fitted to screens of each shape, each rendered in a same-origin frame of that size: on a landscape screen the
// "Text NoClick" card sits beside the statement; on a portrait one the headline runs across the top (in more lines as the
// screen gets taller) and the calls to action stand at the foot, level with the card's button; on a phone the card's
// button is the way in, in place of the signup calls to action. Every size shows the code and the button, lands on one screen and scrolls nowhere sideways.
import { nc } from '~/lib/nc';

const VIEWPORTS = [
    { width: 1920, height: 1080, layout: 'beside', lines: 2 },
    { width: 1440, height: 900, layout: 'beside', lines: 2 },
    { width: 1280, height: 800, layout: 'beside', lines: 2 },
    { width: 1180, height: 820, layout: 'beside', lines: 2 },
    { width: 900, height: 900, layout: 'portrait', lines: 2 },
    { width: 939, height: 1161, layout: 'portrait', lines: 3 },
    { width: 785, height: 1160, layout: 'portrait', lines: 3 },
    { width: 768, height: 1024, layout: 'portrait', lines: 3 },
    { width: 828, height: 1592, layout: 'portrait', lines: 4 },
    { width: 390, height: 844, layout: 'phone', lines: 2 },
] as const;

function load(frame: HTMLIFrameElement) {
    return new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('Responsive hero frame did not load')), 15_000);
        frame.addEventListener(
            'load',
            () => {
                window.clearTimeout(timeout);
                resolve();
            },
            { once: true }
        );
    });
}

const shown = (el: Element | null) => !!el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;

export default async function () {
    // The frames load this same page; only the page that opened them runs the checks.
    if (window.location.pathname !== '/' || new URLSearchParams(window.location.search).has('hero-viewport')) return { helperFrame: true };

    const results = [];
    for (const viewport of VIEWPORTS) {
        const frame = document.createElement('iframe');
        frame.setAttribute('aria-hidden', 'true');
        Object.assign(frame.style, { position: 'fixed', top: '0', left: '0', width: `${viewport.width}px`, height: `${viewport.height}px`, border: '0', opacity: '0', pointerEvents: 'none' });
        document.body.appendChild(frame);
        const loaded = load(frame);
        frame.src = `/?hero-viewport=${viewport.width}x${viewport.height}`;
        await loaded;
        const doc = frame.contentDocument!;
        await nc.wait.until(() => !!doc.querySelector('[data-testid="text-noclick-card"]'), 10_000);

        const hero = doc.querySelector('[data-testid="space-hero"]') as HTMLElement;
        const heading = hero.querySelector('h1') as HTMLElement;
        const actions = doc.querySelector('[data-testid="launchpad-hero-actions"]') as HTMLElement;
        const card = doc.querySelector('[data-testid="text-noclick-card"]') as HTMLElement;
        const qr = card.querySelector('[role="img"]');
        const open = card.querySelector('[data-testid="text-noclick-open"]') as HTMLElement;
        const cardRect = card.getBoundingClientRect();
        const at = `${viewport.width}x${viewport.height}`;

        const headingRect = heading.getBoundingClientRect();
        if (viewport.layout === 'beside') {
            nc.assert.truthy(cardRect.left >= headingRect.right - 1, `${at}: the card sits beside the statement`);
            nc.assert.truthy(cardRect.top < actions.getBoundingClientRect().bottom, `${at}: the card shares the statement's band`);
        } else if (viewport.layout === 'portrait') {
            const actionsRect = actions.getBoundingClientRect();
            nc.assert.truthy(cardRect.top >= headingRect.bottom, `${at}: the headline runs above the card`);
            nc.assert.truthy(cardRect.left >= actionsRect.right, `${at}: the card sits beside the calls to action`);
            nc.assert.truthy(Math.abs(actionsRect.bottom - open.getBoundingClientRect().bottom) <= 2, `${at}: the calls to action stand level with the card's button`);
        } else {
            // A phone texts NoClick rather than signing up: the signup calls to action give way to the card's button.
            nc.assert.falsy(shown(actions), `${at}: no signup calls to action on a phone`);
            nc.assert.truthy(cardRect.top >= headingRect.bottom, `${at}: the card sits under the headline`);
            nc.assert.equal(getComputedStyle(open).backgroundColor, getComputedStyle(heading).color, `${at}: the card's button is the solid one`);
        }
        const lines = Math.round(headingRect.height / (parseFloat(getComputedStyle(heading).fontSize) * 0.92));
        nc.assert.equal(lines, viewport.lines, `${at}: the headline runs ${viewport.lines} lines`);
        nc.assert.truthy(hero.getBoundingClientRect().height <= viewport.height, `${at}: the hero lands on one screen`);
        nc.assert.truthy(shown(qr), `${at}: the code to scan shows`);
        nc.assert.equal(open.textContent?.trim(), 'Open WhatsApp', `${at}: the button under it opens the chat`);
        nc.assert.truthy(doc.documentElement.scrollWidth <= viewport.width, `${at}: nothing scrolls sideways`);

        results.push({ viewport: at, layout: viewport.layout, title: getComputedStyle(heading).fontSize, cardTop: Math.round(cardRect.top), cardLeft: Math.round(cardRect.left) });
        frame.remove();
    }
    return results;
}
