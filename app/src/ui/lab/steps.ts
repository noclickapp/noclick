// The clicks a page lab makes once a scene's view is drawn, for what no address opens (a menu, a dialog, a list in a
// menu): each waits for what it clicks, then clicks it as a person would.
import { useEffect } from 'react';

/** A menu's trigger, pressed as a pointer does (`press`); one of a menu's items by its words (`item`); a button, link
 *  or option whose words or label are these, or that holds a line of just these words (`button`); the first element a
 *  selector finds, clicked (`click`); or words typed into a field (`type`, a selector). `laptop`: only where the
 *  window is a laptop's (a phone's view of it differs, as a menu item that opens an app there). */
export type LabStep = ({ press: string } | { item: string } | { button: string } | { click: string } | { type: string; text: string }) & { laptop?: boolean };

const STEP_WAIT_MS = 10_000;
// A link that opens a new tab leaves the lab, so a step never clicks one.
const CLICKABLE = 'button, a[href]:not([target="_blank"]), [role="menuitem"], [role="option"], [role="tab"]';

const enabled = (el: HTMLElement) => !(el as HTMLButtonElement).disabled;
const says = (el: Element, words: string) => el.textContent?.trim() === words;
const named = (el: HTMLElement, words: string) => says(el, words) || el.getAttribute('aria-label') === words || [...el.querySelectorAll('*')].some((part) => part.childElementCount === 0 && says(part, words));

function find(step: LabStep): HTMLElement | null {
    if ('press' in step) return document.querySelector<HTMLElement>(step.press);
    if ('type' in step) return document.querySelector<HTMLElement>(step.type);
    if ('click' in step) return [...document.querySelectorAll<HTMLElement>(step.click)].find(enabled) ?? null;
    if ('item' in step) return [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) => says(el, step.item)) ?? null;
    return [...document.querySelectorAll<HTMLElement>(CLICKABLE)].find((el) => named(el, step.button) && enabled(el)) ?? null;
}

/** Puts `text` in a field the way typing does, so React hears it. */
function typeInto(el: HTMLElement, text: string) {
    const field = el as HTMLInputElement | HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), 'value')?.set;
    field.focus();
    setter?.call(field, text);
    field.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Makes a scene's clicks in turn, each once what it clicks is drawn; `lab` names the lab in a warning, `phone` says
 *  the window is a phone's. */
export function useSteps(steps: readonly LabStep[] | undefined, lab: string, phone = false) {
    useEffect(() => {
        const taken = steps?.filter((step) => !(phone && step.laptop));
        if (!taken?.length) return;
        let live = true;
        void (async () => {
            for (const step of taken) {
                const end = Date.now() + STEP_WAIT_MS;
                let el = find(step);
                while (live && !el && Date.now() < end) {
                    await new Promise((done) => setTimeout(done, 50));
                    el = find(step);
                }
                if (!live) return;
                if (!el) {
                    console.warn(`[${lab}] Nothing to click for ${JSON.stringify(step)}.`);
                    return;
                }
                // A menu opens on the pointer going down, as a person's press opens it.
                if ('press' in step) el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, pointerType: 'mouse' }));
                else if ('type' in step) typeInto(el, step.text);
                else el.click();
            }
        })();
        return () => {
            live = false;
        };
    }, [steps, lab, phone]);
}
