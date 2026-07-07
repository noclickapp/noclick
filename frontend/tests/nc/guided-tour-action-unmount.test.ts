// Regression test for the agent-chat walkthrough that "never closed": the
// GuidedTourHighlight lives inside the canvas-tab subtree, and its final step's
// action switches to the Interface tab — unmounting the tour mid-handleNext.
// This drives that exact mechanism (the step action unmounts the tour's host
// React root) and asserts onComplete/onClose still fire, so the tour is marked
// done instead of reappearing.
import { nc } from '~/lib/nc';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { GuidedTourHighlight, type TourStep } from '~/components/ui/GuidedTourHighlight';

export default async function () {
  // A visible element for the tour to spotlight.
  const target = document.createElement('button');
  target.setAttribute('data-tour-target', 'nc-unmount-tour-target');
  target.textContent = 'target';
  Object.assign(target.style, { position: 'fixed', top: '120px', left: '120px', width: '80px', height: '32px' });
  document.body.appendChild(target);

  // Host root the tour "lives in" — the step action unmounts it, exactly like
  // switching away from the canvas tab unmounts the walkthrough.
  const host = document.createElement('div');
  document.body.appendChild(host);
  const root = createRoot(host);

  let completed = 0;
  let closed = 0;

  const steps: TourStep[] = [
    {
      target: '[data-tour-target="nc-unmount-tour-target"]',
      title: 'NC Unmount Tour',
      description: 'Final step whose action unmounts the tour host.',
      buttonText: 'Open the chat',
      placement: 'bottom',
      action: () => {
        // Side-effect unmount, mirroring setActiveTab('interface').
        root.unmount();
      },
    },
  ];

  root.render(
    React.createElement(GuidedTourHighlight, {
      steps,
      isActive: true,
      onClose: () => { closed++; },
      onComplete: () => { completed++; },
    })
  );

  // Wait for the portaled CTA button to render.
  const findBtn = () =>
    Array.from(document.querySelectorAll('button')).find(
      b => (b.textContent || '').trim() === 'Open the chat'
    ) as HTMLButtonElement | undefined;
  await nc.wait.until(() => !!findBtn(), 3000);
  const btn = findBtn();
  nc.assert.truthy(btn, 'CTA button should render');

  btn!.click();

  // Past the 150ms fade-out delay in handleNext + a margin.
  await nc.wait.ms(500);

  target.remove();
  try { root.unmount(); } catch { /* already unmounted by the action */ }

  nc.assert.equal(completed, 1, 'onComplete must fire even though the action unmounted the tour host');
  nc.assert.equal(closed, 1, 'onClose must fire even though the action unmounted the tour host');
  return { completed, closed };
}
