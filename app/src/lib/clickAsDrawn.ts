// For tests: a click that lands the moment a render puts its target in the document, before that render's effects
// run. React runs them in a later task when the render wasn't a click's (a navigation, a read landing), and on a busy
// page a person's click lands in between: whatever an effect then resets undoes it (see lib/useChanged.ts).

export interface ClickAsDrawn {
    /** Whether the target was drawn and clicked. */
    clicked: () => boolean;
    stop: () => void;
}

/** Clicks what `find` returns, once, from a mutation observer on the document: right after the render that drew it. */
export function clickAsDrawn(find: () => HTMLElement | null | undefined, click: (target: HTMLElement) => void = (target) => target.click()): ClickAsDrawn {
    let done = false;
    const observer = new MutationObserver(() => {
        if (done) return;
        const target = find();
        if (!target) return;
        done = true;
        observer.disconnect();
        click(target);
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
    return { clicked: () => done, stop: () => observer.disconnect() };
}
