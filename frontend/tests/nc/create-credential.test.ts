// Verifies standalone credential creation: the command palette exposes a
// "Create new credential" action, the create-credential dialog opens with a
// searchable service list, picking a service renders the (node-driven)
// NodeCredentials connect UI, Escape closes it, and the shared
// `noclick:create-credential` event (used by the Credentials settings button)
// opens the same dialog. Run with the nc bridge while authenticated on
// /dashboard.
//
// Note: "is the dialog open" is asserted via the `[data-state="open"]`
// attribute rather than the element's presence. ui/dialog plays an exit
// animation and Radix keeps the closed node mounted until `animationend`, which
// a backgrounded automation tab doesn't reliably fire — so a just-closed dialog
// can linger in the DOM with data-state="closed". Real users see it disappear.
import { nc } from '~/lib/nc';

const PALETTE = '[data-testid="command-palette"]';
const DIALOG = '[data-testid="create-credential-dialog"]';
const OPEN_DIALOG = `${DIALOG}[data-state="open"]`;
const SERVICE_ROW = '[data-testid="credential-service-row"]';

function pressMetaK() {
    window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true })
    );
}

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

// Dispatch a key with focus on the dialog CONTENT (not the search input) — the
// keydown handler lives on the content, so nav must work regardless of focus.
function pressOnContent(key: string) {
    const content = document.querySelector<HTMLElement>(OPEN_DIALOG);
    content?.focus();
    content?.dispatchEvent(
        new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
    );
}

// The highlighted service row carries the bg-white/[0.06] class.
function activeRowIndex(): number {
    return Array.from(
        document.querySelectorAll<HTMLElement>(`${OPEN_DIALOG} ${SERVICE_ROW}`)
    ).findIndex((r) => /bg-white\/\[0\.06\]/.test(r.className));
}

export default async function () {
    // ── Command palette exposes the action ─────────────────────────────────
    pressMetaK();
    await nc.wait.forElement(PALETTE);
    nc.dom.type(`${PALETTE} input`, 'credential');
    await nc.wait.ms(150);

    const actionRow = Array.from(
        document.querySelectorAll<HTMLElement>(`${PALETTE} [data-cmd-index]`)
    ).find((el) => /create new credential/i.test(el.textContent ?? ''));
    nc.assert.truthy(
        actionRow,
        'Command palette lists "Create new credential" when searching "credential"'
    );

    // ── Running it opens the create-credential dialog ──────────────────────
    actionRow!.click();
    await nc.wait.forElement(OPEN_DIALOG);
    nc.assert.truthy(
        !document.querySelector(PALETTE),
        'Palette closes when the credential action runs'
    );
    nc.assert.truthy(
        /Add a credential/i.test(document.querySelector(OPEN_DIALOG)?.textContent ?? ''),
        'Dialog shows the "Add a credential" picker'
    );

    // Service list is populated (lazy registry load resolved).
    await nc.wait.until(
        () => document.querySelectorAll(`${OPEN_DIALOG} ${SERVICE_ROW}`).length > 0,
        4000
    );
    const totalServices = document.querySelectorAll(
        `${OPEN_DIALOG} ${SERVICE_ROW}`
    ).length;
    nc.assert.gt(totalServices, 5, 'Picker renders a list of connectable services');

    // ── Keyboard navigation: ↑/↓ move the highlight and wrap at both ends ───
    const inputSel = `${OPEN_DIALOG} input`;
    pressOnInput(inputSel, 'ArrowDown');
    await nc.wait.ms(80);
    nc.assert.equal(activeRowIndex(), 1, 'ArrowDown moves the highlight to row 2');

    pressOnInput(inputSel, 'ArrowUp');
    pressOnInput(inputSel, 'ArrowUp');
    await nc.wait.ms(80);
    nc.assert.equal(
        activeRowIndex(),
        totalServices - 1,
        'ArrowUp past the top wraps to the last row'
    );

    pressOnInput(inputSel, 'ArrowDown');
    await nc.wait.ms(80);
    nc.assert.equal(
        activeRowIndex(),
        0,
        'ArrowDown past the bottom wraps to the first row'
    );

    // Nav must also work when focus is on the dialog content, not the input
    // (Radix can park focus there) — regression guard for the handler living on
    // the content. From row 0, ArrowUp wraps to the last row.
    pressOnContent('ArrowUp');
    await nc.wait.ms(80);
    nc.assert.equal(
        activeRowIndex(),
        totalServices - 1,
        'Arrow keys navigate even when focus is on the content (not the input)'
    );
    // Return to the top for the deterministic Enter-select below.
    pressOnContent('ArrowDown');
    await nc.wait.ms(80);

    // ── Search narrows the list, Enter selects the top match ───────────────
    nc.dom.type(inputSel, 'slack');
    await nc.wait.ms(150);
    const topRow = document
        .querySelector(`${OPEN_DIALOG} ${SERVICE_ROW}`)
        ?.textContent ?? '';
    nc.assert.truthy(/slack/i.test(topRow), 'Top filtered result is Slack');

    pressOnInput(inputSel, 'Enter');
    await nc.wait.ms(250);
    const dialogText = document.querySelector(OPEN_DIALOG)?.textContent ?? '';
    nc.assert.truthy(
        /Connect Slack/i.test(dialogText),
        'Enter selects the highlighted Slack service and shows the connect step'
    );

    // ── Escape closes the dialog (data-state flips to closed) ──────────────
    pressEscape();
    await nc.wait.until(() => !document.querySelector(OPEN_DIALOG), 3000);
    nc.assert.truthy(
        !document.querySelector(OPEN_DIALOG),
        'Escape closes the create-credential dialog'
    );

    // ── Shared event (Credentials settings button) opens the same dialog ───
    window.dispatchEvent(new CustomEvent('noclick:create-credential'));
    await nc.wait.forElement(OPEN_DIALOG);
    nc.assert.truthy(
        document.querySelector(OPEN_DIALOG),
        'noclick:create-credential opens the dialog from any screen'
    );
    pressEscape();
    await nc.wait.until(() => !document.querySelector(OPEN_DIALOG), 3000);

    return { ok: true, totalServices };
}
