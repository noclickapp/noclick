// Verifies the DynamicOptionsField combobox interaction model: after selecting
// an option the input keeps DOM focus, so Backspace must reopen the dropdown in
// search mode, clicking the field must reopen it (no blur+refocus dance), and
// ArrowDown/Enter must navigate and select. Added with the combobox UX fixes.

import { nc } from '~/lib/nc';

const TEMP_ID = 'nc-test-linear-combobox';
const FIELD = 'input[data-field-key="teamId"]';
const OPTION = '[data-option-index]';

function input(): HTMLInputElement {
  const el = document.querySelector(FIELD) as HTMLInputElement | null;
  nc.assert.truthy(el, 'teamId dynamic options input should be rendered');
  return el!;
}

function visibleOptions(): HTMLButtonElement[] {
  return [...document.querySelectorAll(OPTION)] as HTMLButtonElement[];
}

function teamIdValue(): string {
  const node = nc.nodes.list().find((n: { id: string }) => n.id === TEMP_ID);
  const config = node?.data?.config;
  return String(
    config && typeof config === 'object' && !Array.isArray(config)
      ? (config as Record<string, unknown>).teamId ?? ''
      : ''
  );
}

const mark = (phase: string) => { (window as unknown as Record<string, unknown>).__comboTestPhase = phase; };

export default async function () {
  mark('start');
  // ── Setup: temp Linear node reusing the canvas Linear credential ───────
  const existingLinear = nc.nodes.list().find((n) => n.type === 'automation-linear');
  nc.assert.truthy(existingLinear, 'an automation-linear node with credentials must exist');
  if (!existingLinear) throw new Error('automation-linear node not found');
  const rawCredentialIds = existingLinear.data?.credentialIds;
  const credentialIds =
    rawCredentialIds &&
    typeof rawCredentialIds === 'object' &&
    !Array.isArray(rawCredentialIds)
      ? (rawCredentialIds as Record<string, unknown>)
      : {};
  nc.assert.truthy(Object.keys(credentialIds).length > 0, 'linear node should have a credential');

  nc.nodes.delete(TEMP_ID); // clean slate if a previous run leaked
  nc.nodes.add(TEMP_ID, 'automation-linear', {}, { x: 80, y: 600 });
  nc.nodes.update(TEMP_ID, { operation: 'create_issue', credentialIds });

  try {
    // Open the config panel (self-healing against harness timing)
    await nc.wait.until(() => {
      if (document.querySelector(FIELD)) return true;
      nc.nodes.click(TEMP_ID) || nc.nodes.select(TEMP_ID);
      return false;
    }, 12000, 400);

    mark('panel-open');
    // ── Open + load options ─────────────────────────────────────────────
    // focus() alone can't open here: an unfocused browser tab defers focus
    // events, so drive opening through the onClick path instead.
    nc.dom.focus(FIELD);
    nc.dom.click(FIELD);
    await nc.wait.until(() => visibleOptions().length > 0, 15000, 250);
    const labels = visibleOptions().map(b => (b.textContent || '').trim());
    nc.assert.gt(labels.length, 0, 'options should load from backend');

    mark('options-loaded');
    // ── Select an option by click ───────────────────────────────────────
    nc.dom.click(visibleOptions()[0]);
    await nc.wait.until(() => visibleOptions().length === 0, 3000, 100);
    nc.assert.truthy(teamIdValue(), 'clicking an option should set the value');
    nc.assert.truthy(document.activeElement === input(), 'input keeps DOM focus after selection');

    mark('click-selected');
    // ── Bug 1: Backspace after selecting reopens search ─────────────────
    await nc.wait.until(() => {
      if (visibleOptions().length > 0) return true;
      nc.dom.pressKey(FIELD, 'Backspace');
      return false;
    }, 8000, 400);
    nc.assert.equal(input().value, '', 'backspace should reopen with an empty search box');

    mark('backspace-reopened');
    // ── Bug 2: clicking the still-focused input reopens the dropdown ────
    // (Escape isn't testable here: FlowCanvas's capture-phase handler blurs
    // the input and consumes the event before the component ever sees it.)
    nc.dom.click(visibleOptions()[0]);
    await nc.wait.until(() => visibleOptions().length === 0, 3000, 100);
    // Re-click each poll: real window blur (this runs in a live desktop
    // browser) can legitimately close the dropdown between steps.
    await nc.wait.until(() => {
      if (visibleOptions().length > 0) return true;
      nc.dom.click(FIELD);
      return false;
    }, 8000, 400);

    mark('click-reopened');
    // ── Keyboard: ArrowDown highlights, Enter selects ───────────────────
    const optionCount = visibleOptions().length;
    nc.dom.pressKey(FIELD, 'ArrowDown');
    nc.dom.pressKey(FIELD, 'ArrowDown');
    const expectedIndex = Math.min(1, optionCount - 1);
    const expectedLabel = (visibleOptions()[expectedIndex].textContent || '').trim();
    nc.dom.pressKey(FIELD, 'Enter');
    await nc.wait.until(() => visibleOptions().length === 0, 3000, 100);
    nc.assert.truthy(teamIdValue(), 'enter should select the highlighted option');
    await nc.wait.until(() => input().value.trim() === expectedLabel, 3000, 100);

    mark('keyboard-selected');
    // ── Typing a character while closed seeds a fresh search ────────────
    const seed = expectedLabel[0].toLowerCase();
    await nc.wait.until(() => {
      if (input().value === seed && visibleOptions().length > 0) return true;
      nc.dom.pressKey(FIELD, seed);
      return false;
    }, 8000, 400);

    return { options: labels.length, selected: teamIdValue(), keyboardPick: expectedLabel };
  } finally {
    nc.nodes.delete(TEMP_ID);
  }
}
