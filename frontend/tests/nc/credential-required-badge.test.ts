// Verifies the credential create form uses the shared FieldRequirementBadge
// pills (same treatment as NodeConfig fields) instead of the old red `*` /
// "(optional)" text: required fields show an amber REQUIRED pill that turns
// neutral once filled, and the Name field shows a neutral OPTIONAL pill.
// Run with the nc bridge while authenticated on /dashboard.
import { nc } from '~/lib/nc';

const DIALOG = '[data-testid="create-credential-dialog"]';
const OPEN_DIALOG = `${DIALOG}[data-state="open"]`;
const SERVICE_ROW = '[data-testid="credential-service-row"]';

function pressEscape() {
    document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
    );
}

function pressOnInput(selector: string, key: string) {
    const input = document.querySelector<HTMLInputElement>(selector);
    input?.focus();
    input?.dispatchEvent(
        new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
    );
}

function badges(text: 'Required' | 'Optional'): HTMLElement[] {
    return Array.from(
        document.querySelectorAll<HTMLElement>(`${OPEN_DIALOG} label span`)
    ).filter((s) => s.textContent === text);
}

export default async function () {
    // ── Open the create-credential dialog and pick an API-key service ───────
    window.dispatchEvent(new CustomEvent('noclick:create-credential'));
    await nc.wait.forElement(OPEN_DIALOG);
    await nc.wait.until(
        () => document.querySelectorAll(`${OPEN_DIALOG} ${SERVICE_ROW}`).length > 0,
        4000
    );

    const inputSel = `${OPEN_DIALOG} input`;
    nc.dom.type(inputSel, 'twilio');
    await nc.wait.ms(150);
    const topRow = document.querySelector(`${OPEN_DIALOG} ${SERVICE_ROW}`)?.textContent ?? '';
    nc.assert.truthy(/twilio/i.test(topRow), 'Top filtered result is Twilio');
    pressOnInput(inputSel, 'Enter');

    // ── Open the New Credential form ────────────────────────────────────────
    await nc.wait.until(() => {
        const btn = Array.from(
            document.querySelectorAll<HTMLElement>(`${OPEN_DIALOG} button`)
        ).find((b) => /create (new|another)/i.test(b.textContent ?? ''));
        if (btn) btn.click();
        return /New Credential/i.test(
            document.querySelector(OPEN_DIALOG)?.textContent ?? ''
        );
    }, 5000);

    // ── Old markers are gone ────────────────────────────────────────────────
    const dialogEl = document.querySelector<HTMLElement>(OPEN_DIALOG)!;
    nc.assert.truthy(
        !dialogEl.querySelector('label .text-red-500'),
        'No red asterisk markers in the credential form'
    );
    nc.assert.truthy(
        !/\(optional\)/i.test(dialogEl.textContent ?? ''),
        'No "(optional)" text markers in the credential form'
    );

    // ── Badge pills render with the NodeConfig treatment ────────────────────
    const requiredBadges = badges('Required');
    const optionalBadges = badges('Optional');
    nc.assert.gt(requiredBadges.length, 0, 'Required fields carry a REQUIRED pill');
    nc.assert.gt(optionalBadges.length, 0, 'Name field carries an OPTIONAL pill');
    nc.assert.truthy(
        requiredBadges.every((b) => /bg-amber-100/.test(b.className)),
        'Unfilled required fields show the amber pill'
    );
    nc.assert.truthy(
        optionalBadges.every((b) => /bg-muted/.test(b.className)),
        'Optional fields show the neutral pill'
    );

    // ── Filling a required field drops its pill to neutral ──────────────────
    const requiredInput = dialogEl.querySelector<HTMLInputElement>('input.font-mono');
    nc.assert.truthy(requiredInput, 'Credential form renders a required field input');
    // Walk up to the field block (the div that holds both the label and input).
    let fieldBlock = requiredInput!.parentElement!;
    while (fieldBlock && !fieldBlock.querySelector(':scope > label')) {
        fieldBlock = fieldBlock.parentElement!;
    }
    nc.dom.type(`${OPEN_DIALOG} input.font-mono`, 'ACtest');
    await nc.wait.ms(120);
    const firstBadge = fieldBlock.querySelector('label span')!;
    nc.assert.truthy(
        /bg-muted/.test(firstBadge.className) && !/bg-amber-100/.test(firstBadge.className),
        'Filled required field pill turns neutral'
    );

    // ── Clean up ────────────────────────────────────────────────────────────
    pressEscape();
    await nc.wait.until(() => !document.querySelector(OPEN_DIALOG), 3000);

    return { ok: true, required: requiredBadges.length, optional: optionalBadges.length };
}
