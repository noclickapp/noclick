// Regression test for multi-select <ask multiple="true"> selection asks: the
// drawer must render a "Select all that apply" hint and checkboxes that TOGGLE
// (several options selectable at once, click again to deselect), while default
// selection asks stay single-choice radios. Drives the bridge via the same DOM
// event the real flow uses (pattern from ask-drawer-leak.test.ts).

import { nc } from '~/lib/nc';
import * as wfCtx from '~/components/workflow/WorkflowContext';
import { updateBuilderContext } from '~/lib/builder-context';

const WF = '00000000-0000-0000-0000-000000000ccc';
const OPTIONS = ['Alpha', 'Beta', 'Gamma'];

function dispatchSelectionAsk(multiple: boolean) {
  document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
    detail: {
      inputs: [
        {
          id: 'ask_0',
          nodeId: '',
          label: 'Which alerts?',
          description: '',
          type: 'selection',
          required: true,
          multiple,
          options: OPTIONS.map(o => ({ id: o, label: o })),
        },
      ],
      title: 'Input needed',
      // Unique per run — the bridge remembers dismissed askIds module-wide, so
      // a rerun with a stable id would be silently dropped.
      generationId: `test-gen-${multiple ? 'multi' : 'single'}-${Date.now()}`,
      askId: `test-ask-${multiple ? 'multi' : 'single'}-${Date.now()}`,
      workflowId: WF,
    },
  }));
}

const byText = (text: string): HTMLButtonElement => {
  const btn = Array.from(
    document.querySelectorAll<HTMLButtonElement>('[data-drawer-content] button'),
  ).find(b => (b.textContent || '').trim() === text);
  if (!btn) throw new Error(`option button "${text}" not found`);
  return btn;
};

const isSelected = (text: string) => byText(text).className.includes('bg-foreground/10');

export default async function () {
  const out: Record<string, unknown> = {};

  document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
  await nc.wait.ms(150);
  wfCtx.setCurrentWorkflowId(WF);
  updateBuilderContext({ workflowId: WF, isCanvasMounted: true });
  await nc.wait.ms(300);

  try {
    // ── Multi-select ask: hint + checkboxes that accumulate and toggle ────
    dispatchSelectionAsk(true);
    await nc.wait.forElement('[data-drawer-content]');
    await nc.wait.ms(300);

    const drawerText = document.querySelector('[data-drawer-content]')?.textContent || '';
    out.hintShown = drawerText.includes('Select all that apply');
    nc.assert.equal(out.hintShown, true, 'multi ask shows the select-all hint');

    byText('Alpha').click();
    await nc.wait.ms(150);
    byText('Beta').click();
    await nc.wait.ms(150);
    out.multiBothSelected = isSelected('Alpha') && isSelected('Beta');
    nc.assert.equal(out.multiBothSelected, true, 'two options stay selected together');

    byText('Alpha').click();
    await nc.wait.ms(150);
    out.multiToggleOff = !isSelected('Alpha') && isSelected('Beta');
    nc.assert.equal(out.multiToggleOff, true, 'clicking a selected option deselects it');

    document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
    await nc.wait.ms(300);

    // ── Default (single) ask: radios — a second pick replaces the first ──
    dispatchSelectionAsk(false);
    await nc.wait.forElement('[data-drawer-content]');
    await nc.wait.ms(300);

    out.singleNoHint = !(document.querySelector('[data-drawer-content]')?.textContent || '')
      .includes('Select all that apply');
    nc.assert.equal(out.singleNoHint, true, 'single ask has no select-all hint');

    byText('Alpha').click();
    await nc.wait.ms(150);
    byText('Beta').click();
    await nc.wait.ms(150);
    out.singleOnlyLast = !isSelected('Alpha') && isSelected('Beta');
    nc.assert.equal(out.singleOnlyLast, true, 'single-select keeps only the last pick');
  } finally {
    document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
    wfCtx.setCurrentWorkflowId(undefined);
    updateBuilderContext({ workflowId: undefined, isCanvasMounted: false });
  }

  return out;
}
