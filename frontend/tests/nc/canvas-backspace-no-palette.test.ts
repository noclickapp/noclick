// Regression test for the canvas Backspace behavior. Backspace on the workflow
// canvas (no field focused, nothing selected) used to open the command palette
// as a "Linear-style back" gesture, which was surprising on populated flows. We
// removed that handler, so Backspace must now be a no-op on the canvas while
// ⌘K still opens the palette. Run with the nc bridge on /dashboard with a
// workflow open.
import { nc } from '~/lib/nc';

const PALETTE = '[data-testid="command-palette"]';
const OPEN_EVENT = 'noclick:open-command-palette';

async function closePaletteIfOpen() {
    if (document.querySelector(PALETTE)) {
        document.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
        );
        await nc.wait.ms(80);
    }
}

export default async function () {
    nc.assert.truthy(
        document.querySelector('.react-flow'),
        'Test requires an open workflow canvas'
    );

    await closePaletteIfOpen();

    // Defocus any field so the keydown target is the canvas, not an input — that
    // is exactly the state in which the old handler fired.
    (document.activeElement as HTMLElement | null)?.blur?.();

    // ── Backspace on the canvas must NOT open the palette ───────────────────
    let openEventFired = false;
    const onOpen = () => {
        openEventFired = true;
    };
    window.addEventListener(OPEN_EVENT, onOpen);
    document.body.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true, cancelable: true })
    );
    // Old handler deferred the open via setTimeout(0); wait well past that.
    await nc.wait.ms(150);
    window.removeEventListener(OPEN_EVENT, onOpen);

    nc.assert.falsy(
        openEventFired,
        'Backspace on the canvas must not dispatch the open-palette event'
    );
    nc.assert.falsy(
        document.querySelector(PALETTE),
        'Backspace on the canvas must not open the command palette'
    );

    // ── ⌘K still opens it (we only removed the Backspace path) ──────────────
    window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true })
    );
    await nc.wait.forElement(PALETTE);
    nc.assert.truthy(
        document.querySelector(PALETTE),
        '⌘K should still open the command palette'
    );
    await closePaletteIfOpen();

    return { ok: true, openEventFired };
}
