// What the phone's back and forward swipes show while the finger moves: a picture of the screen each would land on.
// A tap that opens something one level down leaves a copy of the screen it left (its elements, scrolled as they were),
// kept for the place it opened; a swipe back slides the page off that copy, and once the real screen has rendered in
// its place the copy goes. Going back keeps a copy of the screen left, so a swipe the other way brings it back.

/** A copy of the page, ready to show where nobody can touch it. */
export interface Shot {
    root: HTMLElement;
    /** Elements of the copy that were scrolled, and how far, put back once the copy is on screen. */
    scrolled: [HTMLElement, number, number][];
}

/** Each would load again inside the copy (a frame, a player) or copy blank (a canvas): it becomes an empty box its size. */
const REPLACED = new Set(['IFRAME', 'VIDEO', 'AUDIO', 'OBJECT', 'EMBED', 'CANVAS']);
/** How many places keep the screen under them. */
const KEPT = 8;

/** Where the app is: its path and query, which is everything a place in it is. */
export function here(): string {
    return window.location.pathname + window.location.search;
}

/** A copy of the page as it looks now. */
export function capture(page: HTMLElement): Shot {
    const root = page.cloneNode(true) as HTMLElement;
    const originals = page.getElementsByTagName('*');
    const copies = root.getElementsByTagName('*');
    const scrolled: Shot['scrolled'] = [];
    const replaced: [Element, number, number][] = [];
    for (let i = 0; i < originals.length; i++) {
        const el = originals[i];
        if (el.scrollTop || el.scrollLeft) scrolled.push([copies[i] as HTMLElement, el.scrollTop, el.scrollLeft]);
        if (REPLACED.has(el.tagName)) replaced.push([copies[i], (el as HTMLElement).offsetWidth, (el as HTMLElement).offsetHeight]);
    }
    for (const [el, width, height] of replaced) {
        const box = document.createElement('div');
        box.className = el.getAttribute('class') ?? '';
        box.style.cssText = `${el.getAttribute('style') ?? ''};width:${width}px;height:${height}px`;
        el.replaceWith(box);
    }
    // The copy sits in the document beside the page for a moment: nothing of it may answer for the real one (an id, a
    // test's handle, the bar's way back) or take a radio group's choice from it.
    for (const el of [root, ...root.querySelectorAll('[id], [data-testid], [data-phone-back], input[name], [autofocus]')]) {
        el.removeAttribute('id');
        el.removeAttribute('data-testid');
        el.removeAttribute('data-phone-back');
        el.removeAttribute('name');
        el.removeAttribute('autofocus');
    }
    root.removeAttribute('inert');
    root.removeAttribute('data-menu');
    root.removeAttribute('style');
    root.style.cssText = 'position:absolute;inset:0;transform:none;transition:none;z-index:auto';
    return { root, scrolled };
}

/** Puts a copy on screen in `into`, scrolled as the page was, replacing whatever was there. */
export function show(shot: Shot, into: HTMLElement): void {
    into.replaceChildren(shot.root);
    for (const [el, top, left] of shot.scrolled) {
        el.scrollTop = top;
        el.scrollLeft = left;
    }
}

/** True when `to` is a place one or more levels inside `from`: the same page with more chosen in its query (an open
 *  channel in a list, a section in Settings) or a path under it. Back from `to` then lands on `from`. */
export function isDeeper(from: string, to: string): boolean {
    const a = new URL(from, 'https://x');
    const b = new URL(to, 'https://x');
    const pathInside = b.pathname === a.pathname || b.pathname.startsWith(`${a.pathname.replace(/\/$/, '')}/`);
    if (!pathInside) return false;
    for (const [key, value] of a.searchParams) {
        if (b.searchParams.get(key) !== value) return false;
    }
    return b.pathname !== a.pathname || [...b.searchParams.keys()].length > [...a.searchParams.keys()].length;
}

/** The screens under places, newest kept, the oldest let go past `KEPT`. */
export class ScreensUnder {
    private shots = new Map<string, Shot>();

    get(place: string): Shot | null {
        return this.shots.get(place) ?? null;
    }

    keep(place: string, shot: Shot): void {
        this.shots.delete(place);
        this.shots.set(place, shot);
        while (this.shots.size > KEPT) this.shots.delete(this.shots.keys().next().value as string);
    }
}
