// Connecting an account must not empty the step.
//
// The bug this pins: the credential block was derived from live validation, so
// the moment an account was connected it vanished — and since it was often the
// step's ONLY requirement, the body collapsed to "Nothing left to fill in for
// this step" on a step the user had just finished. Every other requirement is
// sticky for exactly this reason; this one was the holdout.
//
// Drives the real popup: opens the gate, finds a step whose requirement is
// credentials, and checks the block survives being satisfied.
import { nc } from '~/lib/nc';

const DIALOG = '[data-incomplete-run-dialog]';

export default async function () {
    nc.ui.clickTab('Workflow');
    await nc.wait.ms(400);
    nc.run.settlePending();
    nc.run.closePopups();
    await nc.wait.ms(400);

    nc.run.button()?.click();
    await nc.wait.forElement(DIALOG, 10000);
    await nc.wait.ms(400);

    // Walk the wizard for a step that asks for credentials.
    let found: string | null = null;
    for (let i = 0; i < 12; i++) {
        const block = document.querySelector('[data-step-credentials]');
        if (block) {
            found = block.getAttribute('data-step-credentials');
            break;
        }
        const next = [
            ...document.querySelectorAll<HTMLButtonElement>(`${DIALOG} button`),
        ].find((b) => b.textContent?.trim() === 'Next');
        if (!next) break;
        next.click();
        await nc.wait.ms(220);
    }
    if (!found) {
        return {
            skipped: 'no step on this canvas asks for credentials',
        };
    }

    const blockText = () => {
        const el = document.querySelector<HTMLElement>(
            `[data-step-credentials="${found}"]`
        );
        return el ? el.innerText.replace(/\s+/g, ' ').trim() : null;
    };
    const bodyText = () =>
        document.querySelector<HTMLElement>(DIALOG)?.innerText ?? '';

    const before = {
        blockPresent: !!blockText(),
        saysRequired: /REQUIRED/i.test(blockText() ?? ''),
    };

    // Satisfy it the way a user does: pick the first account in the select.
    const select = document.querySelector<HTMLSelectElement>(
        `[data-step-credentials="${found}"] select`
    );
    let connected = false;
    if (select && select.options.length > 1) {
        const pick = [...select.options].find((o) => o.value)?.value;
        if (pick) {
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype,
                'value'
            )!.set!;
            setter.call(select, pick);
            select.dispatchEvent(new Event('change', { bubbles: true }));
            connected = true;
            await nc.wait.ms(900);
        }
    }

    if (!connected) {
        // Nothing to pick — this canvas has no saved account for that service.
        // Say so rather than returning booleans that look like a pass.
        return {
            stepId: found,
            skipped: 'no saved credential to select for this step',
            blockPresent: before.blockPresent,
            saysRequired: before.saysRequired,
        };
    }

    nc.assert.truthy(
        blockText(),
        'the credential block must survive being satisfied'
    );
    nc.assert.truthy(
        /DONE/i.test(blockText() ?? ''),
        'and flip to Done rather than disappearing'
    );
    nc.assert.falsy(
        bodyText().includes('Nothing left to fill in'),
        'a step the user just finished must not read as empty'
    );

    return {
        stepId: found,
        before,
        connected,
        // The point of the fix: still listed, now Done, and the step body is
        // NOT the empty-state message.
        blockStillListed: !!blockText(),
        saysDone: /DONE/i.test(blockText() ?? ''),
        showsEmptyState: bodyText().includes('Nothing left to fill in'),
    };
}
