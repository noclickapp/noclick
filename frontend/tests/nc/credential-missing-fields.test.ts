// Verifies how the connect form says what's missing: no REQUIRED pills and no name asked up front, a Connect button
// that is never greyed out, and pressed early, "Enter the …" under each empty field, which clears as that field is
// filled. Run with the nc bridge while authenticated on /dashboard.
import { nc } from '~/lib/nc';

const DIALOG = '[data-testid="create-credential-dialog"]';
const OPEN_DIALOG = `${DIALOG}[data-state="open"]`;
const SERVICE_ROW = '[data-testid="credential-service-row"]';

function pressEscape() {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

function pressOnInput(selector: string, key: string) {
    const input = document.querySelector<HTMLInputElement>(selector);
    input?.focus();
    input?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

const missing = () =>
    Array.from(document.querySelectorAll<HTMLElement>(`${OPEN_DIALOG} form [role="alert"], ${OPEN_DIALOG} form p`)).filter((p) =>
        /^Enter the /.test(p.textContent ?? '')
    );

export default async function () {
    // ── Open the connect dialog on an app connected by key ──────────────────
    window.dispatchEvent(new CustomEvent('noclick:create-credential'));
    await nc.wait.forElement(OPEN_DIALOG);
    await nc.wait.until(() => document.querySelectorAll(`${OPEN_DIALOG} ${SERVICE_ROW}`).length > 0, 4000);

    const inputSel = `${OPEN_DIALOG} input`;
    nc.dom.type(inputSel, 'twilio');
    await nc.wait.ms(150);
    const topRow = document.querySelector(`${OPEN_DIALOG} ${SERVICE_ROW}`)?.textContent ?? '';
    nc.assert.truthy(/twilio/i.test(topRow), 'Top filtered result is Twilio');
    pressOnInput(inputSel, 'Enter');
    await nc.wait.until(() => !!document.querySelector(`${OPEN_DIALOG} form button[type="submit"]`), 8000);

    const dialogEl = document.querySelector<HTMLElement>(OPEN_DIALOG)!;
    const form = dialogEl.querySelector<HTMLFormElement>('form')!;
    const submit = form.querySelector<HTMLButtonElement>('button[type="submit"]')!;

    // ── Nothing marks every field, and nothing asks for a name ──────────────
    nc.assert.truthy(!/\bRequired\b/.test(form.textContent ?? ''), 'No REQUIRED pill on the fields');
    nc.assert.truthy(!Array.from(form.querySelectorAll('label')).some((l) => l.textContent?.trim() === 'Name'), 'No name asked up front');

    // ── Never greyed out: pressed early, it says what's missing ─────────────
    nc.assert.truthy(!submit.disabled, 'Connect is never disabled');
    submit.click();
    await nc.wait.until(() => missing().length > 0, 3000);
    const before = missing().length;
    nc.assert.gt(before, 0, 'Each empty required field says what to enter');
    nc.assert.truthy(!!document.querySelector(OPEN_DIALOG), 'Nothing was sent: the dialog stays on the form');

    // ── Filling a field clears its own line ────────────────────────────────
    const firstEmpty = form.querySelector<HTMLInputElement>('input[aria-invalid="true"]') ?? form.querySelector<HTMLInputElement>('input');
    nc.assert.truthy(firstEmpty, 'The form has a field to fill');
    firstEmpty!.focus();
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(firstEmpty, 'ACtest');
    firstEmpty!.dispatchEvent(new Event('input', { bubbles: true }));
    await nc.wait.ms(150);
    nc.assert.equal(missing().length, before - 1, 'Filling a field clears its line and leaves the others');

    // ── Clean up ────────────────────────────────────────────────────────────
    pressEscape();
    await nc.wait.until(() => !document.querySelector(OPEN_DIALOG), 3000);

    return { ok: true, missing: before };
}
