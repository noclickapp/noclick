/**
 * Live E2E for the Run button's unconfigured-steps gate.
 *
 * Pressing Run used to start the workflow regardless of whether its steps were
 * configured, so a half-filled template ran until the backend rejected the first
 * hole. Run now raises a popup naming each unready step.
 *
 * Deliberately starts no run: every assertion here keeps the popup open or
 * dismisses it, so the test costs nothing and cannot leave an execution behind.
 * Probe nodes are added through the local-only harness (no broadcast, no save)
 * and removed at the end.
 */
import { nc } from '~/lib/nc';
import { credentialsPulseKey, onPulseRequested } from '~/lib/pulseHighlight';

const DIALOG = '[data-incomplete-run-dialog]';

/** Budget for anything that waits on a React commit.
 *
 *  This suite normally runs against a BACKGROUND tab, and Chrome clamps
 *  setTimeout there — including the polls inside nc.wait — so every wait costs
 *  roughly an order of magnitude more wall-clock than it does with the tab
 *  focused. Nothing here is slow in front of a user; the budget is for the
 *  harness, not the product. */
const SLOW_MS = 20000;

function runButton(): HTMLElement {
    const btn = Array.from(document.querySelectorAll('button')).find(
        (b) => b.textContent?.trim() === 'Run'
    );
    if (!btn) throw new Error('Run button not found');
    return btn as HTMLElement;
}

function dialogButton(label: string): HTMLElement {
    const dialog = document.querySelector(DIALOG);
    if (!dialog) throw new Error('incomplete-run dialog not open');
    const btn = Array.from(dialog.querySelectorAll('button')).find(
        (b) => b.textContent?.trim() === label
    );
    if (!btn) throw new Error(`"${label}" not found in the dialog`);
    return btn as HTMLElement;
}

/** Jump the wizard to a given step via its progress segment.
 *
 *  Deliberately not paging with Next: on a real canvas the intermediate steps
 *  can be nodes with dynamic-options fields, and rendering each one fires a
 *  backend load_options round trip. Walking past three of those made this time
 *  out on the machine, not on the code. The segments are real navigation the
 *  user has, and a jump renders exactly one step. */
async function stepTo(nodeId: string) {
    const dialog = () => document.querySelector(DIALOG);
    // Re-query and re-click per attempt. The popup re-renders whenever the graph
    // changes, so a segment captured a moment earlier can already be detached —
    // clicking it then does nothing and the wait blames navigation.
    for (let attempt = 0; attempt < 4; attempt++) {
        if (dialog()?.getAttribute('data-current-step') === nodeId) return;
        const ids = (dialog()?.getAttribute('data-step-ids') ?? '').split(',');
        const target = ids.indexOf(nodeId);
        if (target < 0) {
            throw new Error(
                `${nodeId} is not one of the wizard's steps: ${ids}`
            );
        }
        const segment = dialog()?.querySelectorAll(
            'button[aria-label^="Go to"]'
        )[target];
        if (!segment) throw new Error(`no progress segment for ${nodeId}`);
        (segment as HTMLElement).click();
        try {
            await nc.wait.until(
                () => dialog()?.getAttribute('data-current-step') === nodeId,
                2500
            );
            return;
        } catch {
            /* re-render swallowed the click; take the segment again */
        }
    }
    throw new Error(`could not reach ${nodeId} in the wizard`);
}

/** Escape first — that is the path being tested — then fall back to the close
 *  button. Escape depends on Radix's key handler being mounted and focused,
 *  which is not guaranteed when the popup is reopened right after a close, and
 *  a cleanup that cannot close the dialog strands the next run behind it. */
async function closeDialog() {
    for (const attempt of [0, 1]) {
        if (!document.querySelector(DIALOG)) return;
        if (attempt === 0) {
            document.dispatchEvent(
                new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
            );
        } else {
            const dialog = document.querySelector(DIALOG)!;
            const close = Array.from(dialog.querySelectorAll('button')).pop();
            (close as HTMLElement | undefined)?.click();
        }
        try {
            await nc.wait.until(() => !document.querySelector(DIALOG), 8000);
            return;
        } catch {
            /* try the next way in */
        }
    }
    throw new Error('the popup would not close via Escape or its close button');
}

/** The probes, and how to (re)create them.
 *
 *  Re-checked before each phase rather than added once: nc.nodes.add writes
 *  local-only state, so a server re-sync — which happens on any canvas someone
 *  is actively editing — silently drops them. When it landed mid-run the popup
 *  still listed the node (the step set was captured before the wipe) while the
 *  hand-off found nothing to select, and the failure pointed at the wrong
 *  thing entirely. */
const PROBES: Array<
    [string, string, Record<string, unknown>, { x: number; y: number }]
> = [
    // An operation is required, not incidental: with none chosen the step's
    // only requirement is the action picker — credentials are per-operation, so
    // nothing else about the node is knowable yet — and the credential
    // assertions below would have nothing to run against.
    ['nc_gate_live', 'automation-slack', {}, { x: 240, y: 240 }],
    ['nc_gate_off', 'automation-slack', {}, { x: 240, y: 400 }],
    // Only gap is a plain text field, so the typing assertions have a control
    // they own. Picking "whatever editor is on screen" grabbed a
    // dynamic-options combobox on a real canvas, where typing is a search
    // query and never fills the field.
    ['nc_gate_text', 'agent', { model: 'opencode' }, { x: 240, y: 560 }],
];

/** The metadata each probe needs to present the gap this suite asserts on.
 *
 *  Slack needs an action: with none chosen the step's only requirement is the
 *  action picker, because credentials are per-operation and nothing else about
 *  the node is knowable yet. It also needs NO credential — and that has to be
 *  re-asserted every run, because the popup's inline credential form selects
 *  the user's existing account, which is the point of the feature but leaves
 *  the probe satisfied for the next run. */
function metaFor(id: string): Record<string, unknown> {
    if (id === 'nc_gate_text')
        return {
            credentialIds: { agent_opencode: 'nc-probe' },
            // Explicit empties: node updates MERGE into data.config, so
            // re-applying the declared config cannot clear what a previous run
            // typed. The gap has to be restored by name.
            config: { model: 'opencode', message: '' },
        };
    return {
        operation: 'send_message_to_channel',
        credentialIds: {},
        config: { channel: '', text: '' },
    };
}

async function ensureProbes() {
    for (const [id, type, config, position] of PROBES) {
        if (!nc.node(id)) {
            nc.nodes.add(id, type, config, position);
            await nc.wait.until(() => !!nc.node(id), SLOW_MS);
        }
        // Reset every run, not just on create. This suite FILLS the gaps it
        // asserts on, so a probe surviving from a previous run is no longer
        // incomplete — it drops out of the step set and the next run fails
        // looking for a step that is now perfectly fine.
        nc.nodes.update(id, { ...metaFor(id) });
        if (id === 'nc_gate_off') nc.nodes.update(id, { disabled: true });
    }
    await nc.wait.until(
        () => nc.node('nc_gate_off')?.disabled === true,
        SLOW_MS
    );
}

export default async function () {
    const results: Record<string, unknown> = {};

    // A live unconfigured step and a disabled one. Slack with no operation is
    // incomplete; the disabled twin must not appear, because the backend skips
    // disabled nodes at execution and so it cannot be why this run would fail.
    // nc.node() flattens node.data, so `disabled` reads top-level in there.
    await ensureProbes();

    try {
        // 0. An ordinary trip to the credentials tab requests no pulse — an
        //    indicator that fires on every visit is one people stop seeing.
        //    First, before any popup exists, so it is unambiguously the manual
        //    path — and because clicking the tab opens the config panel, whose
        //    commit would otherwise be competing with the next Run click.
        const idleRequests: string[] = [];
        const stopIdleWatch = onPulseRequested((key) => idleRequests.push(key));
        Array.from(document.querySelectorAll('button'))
            .find((b) => b.textContent?.trim() === 'Credentials')
            ?.click();
        await nc.wait.ms(200);
        stopIdleWatch();
        nc.assert.deepEqual(
            idleRequests,
            [],
            'opening the credentials tab by hand must not request a pulse'
        );
        results.manualCredentialsOpenDidNotPulse = true;

        // 1. Run is intercepted rather than starting a doomed run.
        runButton().click();
        await nc.wait.forElement(DIALOG, SLOW_MS);
        const dialog = document.querySelector(DIALOG)!;
        results.dialogOpened = true;

        // 2. The live step is in the wizard's step set and the disabled twin is
        //    not. Read from data-step-ids rather than the DOM, because the
        //    wizard renders one step at a time — and asserted by id rather than
        //    by count, since the canvas may hold unconfigured steps of its own
        //    and both probes are the same node type.
        const listed = (dialog.getAttribute('data-step-ids') ?? '').split(',');
        nc.assert.includes(
            listed,
            'nc_gate_live',
            'the live step must be included'
        );
        nc.assert.falsy(
            listed.includes('nc_gate_off'),
            'a disabled step is skipped at execution, so it must not block the run'
        );
        results.listedSteps = listed;

        // ── Everything below runs inside this ONE open ──────────────────────
        // The popup is deliberately never reopened. Opening it commits React
        // state and, for the hand-offs, a cascade that polls on a CHAINED
        // setTimeout(40); Chrome clamps chained timers to ~1s in a hidden tab
        // and to ~1/min once it has been hidden a while. This suite normally
        // runs against a background tab, so each reopen cost tens of seconds
        // and the failures read as feature bugs when they were the clamp.
        // Measured: the same click settles in ~1.2s focused.
        //
        // For the same reason the panel-opening half of each hand-off is not
        // asserted here at all — it cannot be observed at any sane timeout. It
        // was verified by hand in a focused tab: 70% height, node visible in
        // the strip above the panel, credentials tab active, ring pulsing.
        // What IS asserted is what each click does synchronously, which is
        // where the wiring lives.

        // 3. A missing field is filled in the popup itself, and the editor
        //    survives typing. This is the whole feature's load-bearing detail: a
        //    field stops being "missing" on the first keystroke, so an editor
        //    derived from live validation unmounts mid-word and drops focus.
        //    Runs against the probe's own plain text field, not whatever editor
        //    happens to be on screen.
        {
            await stepTo('nc_gate_text');
            const fieldWrap = document.querySelector(
                '[data-step-field="message"]'
            );
            const editor = fieldWrap?.querySelector(
                'textarea, input[type="text"]'
            ) as HTMLTextAreaElement | HTMLInputElement | null;
            results.inlineEditorFound = !!editor;
            if (editor && fieldWrap) {
                const box = editor;
                const before = box.value;
                const setValue = Object.getOwnPropertyDescriptor(
                    box instanceof HTMLTextAreaElement
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype,
                    'value'
                )!.set!;
                box.focus();
                for (const partial of ['n', 'nc', 'nc ', 'nc t', 'nc te']) {
                    setValue.call(box, partial);
                    box.dispatchEvent(new Event('input', { bubbles: true }));
                    await nc.wait.ms(30);
                }
                nc.assert.truthy(
                    document.contains(box),
                    'the editor must stay mounted across keystrokes'
                );
                nc.assert.equal(
                    document.activeElement,
                    box,
                    'focus must survive the re-validation each keystroke triggers'
                );
                nc.assert.equal(
                    box.value,
                    'nc te',
                    'every keystroke should land'
                );
                results.typingSurvivedRevalidation = true;

                // The step re-validates live off the real node data.
                await nc.wait.until(
                    () =>
                        fieldWrap.getAttribute('data-field-filled') === 'true',
                    SLOW_MS
                );
                results.fieldMarkedFilled = true;

                setValue.call(box, before);
                box.dispatchEvent(new Event('input', { bubbles: true }));
                await nc.wait.ms(50);
            }
        }

        // 4. The gate is a prompt, not a lock: with the popup up and a field
        //    just edited, no run has been started behind it.
        nc.assert.truthy(
            !!Array.from(document.querySelectorAll('button')).find(
                (b) => b.textContent?.trim() === 'Run'
            ),
            'the Run button must not have flipped to Stop'
        );
        results.noRunStarted = true;

        // 5. The credential requirement is connected IN the popup — the whole
        //    point of embedding NodeCredentials there is that satisfying it
        //    does not cost the user their place.
        await stepTo('nc_gate_live');
        nc.assert.truthy(
            document.querySelector('[data-step-credentials="nc_gate_live"]'),
            'the step must list its credential requirement in the popup'
        );
        results.credentialRequirementListed = true;

        // 6. LAST, because nothing after it is observable here: the escape
        //    hatch beneath it targets THAT node's credentials. Asserted on the
        //    pulse request, which the click makes synchronously and which
        //    carries the node id — the half the DOM could never distinguish,
        //    since a config and a credentials hand-off look identical from
        //    outside. Everything the click sets in motion afterwards is the
        //    deferred panel cascade described above, including the popup's own
        //    dismissal.
        const requested: string[] = [];
        const stopWatching = onPulseRequested((key) => requested.push(key));
        dialogButton('Open the full credentials panel').click();
        stopWatching();
        nc.assert.deepEqual(
            requested,
            [credentialsPulseKey('nc_gate_live')],
            'Connect must request the pulse for that node, exactly once'
        );
        results.connectRequestedCredentialPulse = true;
    } catch (err) {
        throw new Error(
            `${(err as Error).message} | diagnostics: ${JSON.stringify(results)}`
        );
    } finally {
        // Best-effort: the last step deliberately leaves a deferred panel commit
        // in flight, and a cleanup that cannot close the popup must not turn a
        // passing run into a failing one. The probes go regardless.
        await closeDialog().catch(() => {});
        nc.nodes.delete('nc_gate_live');
        nc.nodes.delete('nc_gate_off');
        nc.nodes.delete('nc_gate_text');
    }

    return results;
}
