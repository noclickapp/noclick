// Verifies the list widget (ui:widget="list", e.g. Gmail send "to") no longer
// needs Enter to save: typing into the trailing empty box auto-appends a fresh
// empty box below, and removing a row collapses it. The box only appends
// through the same commit() that calls onChange (the autosave), so the DOM
// behavior asserted here exercises the autosave path end to end. Config
// persistence itself rides the shared handleFieldChange→onChange pipeline used
// by every field (verified manually; the harness's getNodes() reflects it with
// multi-second YJS-sync lag, too flaky to poll here).
import { nc } from '~/lib/nc';

const FIELD = 'to';

function listInputs(): HTMLInputElement[] {
    const container = document.querySelector(`[data-field-key="${FIELD}"]`);
    if (!container) return [];
    return [...container.querySelectorAll('input[type="text"]')] as HTMLInputElement[];
}

// React's controlled inputs ignore `.value = x; dispatch`. Use the native
// setter so onChange sees the new value, the same way nc.dom.type does.
function typeInto(input: HTMLInputElement, text: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

export default async function () {
    const id = 'gmail-list-test';
    nc.nodes.delete(id); // clean slate if a previous run leaked
    nc.nodes.add(id, 'automation-gmail', {}, { x: 80, y: 600 });
    nc.nodes.update(id, { operation: 'send_email_message' });

    // Open the config panel (re-dispatch select until the field mounts), then
    // settle so the select-driven pan/fitView animation stops re-rendering it.
    await nc.wait.until(() => {
        if (listInputs().length > 0) return true;
        nc.nodes.select(id);
        return false;
    }, 15000, 600);
    await nc.wait.ms(1500);

    // Starts with exactly one empty box.
    await nc.wait.until(() => listInputs().length === 1);

    // Typing in the trailing box auto-appends a fresh empty box — no Enter.
    typeInto(listInputs()[0], 'a@b.com');
    await nc.wait.until(() => listInputs().length === 2, 8000);
    nc.assert.equal(listInputs()[0].value, 'a@b.com', 'first value retained');
    nc.assert.equal(listInputs()[1].value, '', 'appended box is empty');

    // Second value into the new trailing box: appends again.
    typeInto(listInputs()[1], 'c@d.com');
    await nc.wait.until(() => listInputs().length === 3, 8000);
    nc.assert.equal(listInputs()[1].value, 'c@d.com', 'second value retained');
    nc.assert.equal(listInputs()[2].value, '', 'trailing box stays empty');

    // The trailing empty box carries no remove button (nothing to remove);
    // filled rows do. So there are exactly two remove buttons for two values.
    const removeButtons = () =>
        document.querySelectorAll(`[data-field-key="${FIELD}"] button[aria-label="Remove item"]`);
    nc.assert.equal(removeButtons().length, 2, 'only filled rows get a remove button');

    // Removing the first row collapses it; the second value shifts up.
    (removeButtons()[0] as HTMLButtonElement).click();
    await nc.wait.until(() => listInputs().length === 2, 8000);
    nc.assert.equal(listInputs()[0].value, 'c@d.com', 'remove drops the first row');

    nc.nodes.delete(id);
    return { passed: true };
}
